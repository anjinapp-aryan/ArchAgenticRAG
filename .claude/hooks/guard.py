#!/usr/bin/env python3
"""Claude Code hooks for ArchAgenticRAG. Standard library only. Fails open.

  guard.py pre-write    PreToolUse  Write|Edit        ask before changing a frozen artifact
  guard.py pre-bash     PreToolUse  Bash|PowerShell   destructive-command and commit gates
  guard.py post-write   PostToolUse Write|Edit        run the pin or lint tests when relevant files change
  guard.py verify       (command line)                compare frozen artifacts with the register

Rationale and measured behaviour: docs/ai-development/STUDIO_REUSE_AUDIT.md and
PRODUCTIVITY_VALIDATION.md. The register is docs/ai-development/frozen-artifacts.json.

Only explicit rules block. Any internal error exits 0 so a bug here can never stop work.
Output is ASCII and never contains a secret value: variable names and file names only.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REGISTER = ROOT / "docs" / "ai-development" / "frozen-artifacts.json"
ENV_FILE = ROOT / ".env"
MAIN_BRANCHES = {"main", "master"}
# Set by the user in their own environment before starting Claude Code. An agent cannot set the hook's environment
# from inside a tool call, so this is a human-only override for the irreversible cases below.
OVERRIDE_ENV = "ARCHAGENTICRAG_ALLOW_DESTRUCTIVE"

# Key shapes. Anchored so ordinary words such as "task-based-evaluation" cannot match "sk-".
SECRET_SHAPES = re.compile(
    r"(?<![A-Za-z0-9])(?:AIza[0-9A-Za-z_-]{20,}|AQ\.Ab8[0-9A-Za-z_-]{10,}|gsk_[0-9A-Za-z]{20,}"
    r"|nvapi-[0-9A-Za-z_-]{20,}|xai-[0-9A-Za-z]{20,}|csk-[0-9A-Za-z]{20,}|sk-[0-9A-Za-z_-]{20,})"
)
SECRET_NAME = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD)")
PIN_TRIGGERS = (
    "eval/configs/*.yaml",
    "src/archagenticrag/evaluation/config.py",
    "src/archagenticrag/rag/settings.py",
    "src/archagenticrag/providers.py",
)
STUDIO_TRIGGERS = ("AGENTS.md", "CLAUDE.md", ".claude/*", "docs/ai-development/*", "tests/ai_development/*")
HEREDOC = re.compile(r"<<-?\s*(['\"]?)(\w+)\1[^\n]*\n.*?\n[ \t]*\2\b", re.S)
MUTATING = {"rm", "mv", "rmdir", "del", "truncate", "shred", "tee", "remove-item", "move-item", "rename-item", "set-content", "clear-content"}


# ---------- small helpers ----------


def load_register() -> dict:
    return json.loads(REGISTER.read_text(encoding="utf-8"))


def rel(path_str: str) -> str | None:
    """Project-relative POSIX path, or None when the path is outside the project."""
    try:
        p = Path(path_str)
        p = p if p.is_absolute() else ROOT / p
        return p.resolve().relative_to(ROOT).as_posix()
    except (ValueError, OSError):
        return None


def matches(path: str, patterns) -> bool:
    return any(fnmatch.fnmatchcase(path, pat) for pat in patterns)


def is_protected(path: str, reg: dict) -> bool:
    return matches(path, reg["protected_globs"]) or path in reg["fingerprints"]


def decision(kind: str, reason: str) -> dict:
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": kind, "permissionDecisionReason": reason}}


def user_allows_destructive() -> bool:
    return os.environ.get(OVERRIDE_ENV) == "1"


def is_irreversible(path: str) -> bool:
    """Run results are gitignored: the only copy is on this machine."""
    return path == "eval/results" or path.startswith("eval/results/")


def frozen_change(path: str) -> dict | None:
    """Decision for a change to a frozen artifact.

    Irreversible targets are denied, because an 'ask' is approved automatically in bypass-permissions mode
    (observed in a live probe, 2026-11-03). Files that git can restore only need confirmation.
    """
    if is_irreversible(path):
        if user_allows_destructive():
            return None
        return decision(
            "deny",
            f"{path} is run evidence that exists only on this machine (gitignored) and cannot be restored. An agent may not change it. "
            f"If the user really wants this, they must set {OVERRIDE_ENV}=1 in the environment before starting Claude Code.",
        )
    return decision("ask", f"{path} is a frozen artifact (docs/ai-development/EXPERIMENT_RULES.md). Continue only if the user authorised changing it; otherwise create a new file.")


def project_python() -> str | None:
    for candidate in (ROOT / ".venv" / "Scripts" / "python.exe", ROOT / ".venv" / "bin" / "python"):
        if candidate.exists():
            return str(candidate)
    return None


def git(*args: str) -> str:
    out = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=20)
    return out.stdout if out.returncode == 0 else ""


def current_branch() -> str:
    return git("branch", "--show-current").strip()


# ---------- frozen artifacts ----------


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fingerprints(paths: list[str]) -> dict[str, str]:
    py = project_python()
    if not py or not paths:
        return {}
    code = (
        "import json,sys\nfrom archagenticrag.evaluation.config import load_config\n"
        "print(json.dumps({p: load_config(p).fingerprint() for p in sys.argv[1:]}))"
    )
    out = subprocess.run([py, "-c", code, *paths], cwd=ROOT, capture_output=True, text=True, timeout=60)
    return json.loads(out.stdout.strip().splitlines()[-1]) if out.returncode == 0 and out.stdout.strip() else {}


def verify(reg: dict) -> list[tuple[str, str, str]]:
    """(status, name, detail) rows. Status is OK, MISMATCH or SKIPPED (not present on this machine)."""
    rows: list[tuple[str, str, str]] = []
    for name, expected in reg["files"].items():
        f = ROOT / name
        if not f.exists():
            local_only = name.startswith("eval/results/")  # gitignored: absent on a fresh clone
            rows.append(("SKIPPED" if local_only else "MISMATCH", name, "not present on this machine" if local_only else "file missing"))
        elif sha256(f) != expected:
            rows.append(("MISMATCH", name, "sha256 differs from the register"))
        else:
            rows.append(("OK", name, ""))
    got = fingerprints(list(reg["fingerprints"]))
    for name, expected in reg["fingerprints"].items():
        if not got:
            rows.append(("SKIPPED", name, "no project virtualenv to compute fingerprints"))
        elif got.get(name) != expected:
            rows.append(("MISMATCH", name, f"fingerprint {got.get(name)} != {expected}"))
        else:
            rows.append(("OK", name, ""))
    return rows


# ---------- secrets ----------


def env_secrets() -> dict[str, str]:
    """Values of secret-looking variables in .env (at least 12 characters). Never printed."""
    secrets: dict[str, str] = {}
    if not ENV_FILE.exists():
        return secrets
    for line in ENV_FILE.read_text(encoding="utf-8", errors="replace").splitlines():
        name, sep, value = line.partition("=")
        value = value.strip().strip("'\"")
        if sep and SECRET_NAME.search(name) and len(value) >= 12:
            secrets[name.strip()] = value
    return secrets


def scan_diff(diff: str, secrets: dict[str, str]) -> list[str]:
    """Findings for the added lines of a unified diff: file and variable names only."""
    findings: list[str] = []
    current = "?"
    for line in diff.splitlines():
        if line.startswith("+++ "):
            current = line[6:] if line.startswith("+++ b/") else line[4:]
            continue
        if not line.startswith("+"):
            continue
        for name, value in secrets.items():
            if value in line:
                findings.append(f"value of {name} from .env appears in {current}")
        if SECRET_SHAPES.search(line):
            findings.append(f"key-shaped text appears in {current}")
    return sorted(set(findings))


def commit_findings(args: list[str]) -> list[str]:
    stage_all = any(a == "--all" or (re.fullmatch(r"-[A-Za-z]+", a) and "a" in a) for a in args if not a.startswith("--") or a == "--all")
    base = ["diff", "HEAD"] if stage_all else ["diff", "--cached"]
    findings = []
    for name in git(*base, "--name-only").splitlines():
        if re.search(r"(^|/)\.env($|\.)", name) and not name.endswith(".example"):
            findings.append(f"{name} is an environment file and must not be committed")
    findings += scan_diff(git(*base, "-U0"), env_secrets())
    for status, name, detail in verify(load_register()):
        if status == "MISMATCH":
            findings.append(f"frozen artifact changed: {name} ({detail})")
    return findings


# ---------- shell command analysis ----------


def split_commands(cmd: str) -> list[str]:
    """Split on unquoted && || ; | and newlines. Backslash-newline continues a command; heredoc bodies are dropped."""
    cmd = HEREDOC.sub(" ", cmd.replace("\\\r\n", " ").replace("\\\n", " "))
    out: list[str] = []
    cur: list[str] = []
    quote = None
    i = 0
    while i < len(cmd):
        ch = cmd[i]
        if quote:
            cur.append(ch)
            if ch == "\\" and quote == '"' and i + 1 < len(cmd):
                cur.append(cmd[i + 1])
                i += 1
            elif ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
            cur.append(ch)
        elif cmd.startswith(("&&", "||"), i):
            out.append("".join(cur))
            cur = []
            i += 1
        elif ch in ";|\n":
            out.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
        i += 1
    out.append("".join(cur))
    return [s.strip() for s in out if s.strip()]


def tokens(seg: str) -> list[str]:
    import shlex

    seg = seg.replace("\\", "/")
    try:
        return shlex.split(seg, posix=True)
    except ValueError:
        return seg.split()


def git_parts(toks: list[str]) -> tuple[str, list[str]] | None:
    t = list(toks)
    while t and re.match(r"\w+=", t[0]):
        t.pop(0)
    if not t or t[0] != "git":
        return None
    i = 1
    while i < len(t) and t[i].startswith("-"):
        i += 2 if t[i] in ("-C", "-c") else 1
    return (t[i], t[i + 1 :]) if i < len(t) else None


def has_flag(args: list[str], short: str, long_: str | tuple = ()) -> bool:
    longs = (long_,) if isinstance(long_, str) else long_
    return any(a in longs or (re.fullmatch(r"-[A-Za-z]+", a) is not None and short in a) for a in args)


def collection_state(url: str, name: str) -> str:
    try:
        with urllib.request.urlopen(f"{url.rstrip('/')}/collections/{name}", timeout=2) as resp:
            return "exists" if resp.status == 200 else "unknown"
    except urllib.error.HTTPError as exc:
        return "missing" if exc.code == 404 else "unknown"
    except Exception:
        return "unknown"


def ingest_target(toks: list[str]) -> tuple[str, str] | None:
    cfg = next((t for t in toks if t.endswith((".yaml", ".yml"))), None)
    if not cfg:
        return None
    path = ROOT / cfg
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8", errors="replace")
    coll = re.search(r"^\s*collection:\s*([A-Za-z0-9_-]+)", text, re.M)
    url = re.search(r"^\s*url:\s*(http\S+)", text, re.M)
    return (coll.group(1), url.group(1) if url else "http://localhost:6333") if coll else None


def protected_candidates(seg: str, reg: dict) -> list[str]:
    found = []
    for m in re.finditer(r"(?:eval|data)/[^\s\"'<>|;&]*", seg.replace("\\", "/")):
        cand = m.group(0).rstrip("/")
        if is_protected(cand, reg):
            found.append(cand)
    return found


def redirect_targets(seg: str) -> list[str]:
    """Targets of unquoted > and >> redirects. Quoted text (a sed script containing '->') and fd duplication (2>&1) are ignored."""
    seg = seg.replace("\\", "/")
    targets: list[str] = []
    quote = None
    i = 0
    while i < len(seg):
        ch = seg[i]
        if quote:
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch == ">":
            i += 1
            if i < len(seg) and seg[i] == ">":
                i += 1
            if i < len(seg) and seg[i] == "&":
                continue
            while i < len(seg) and seg[i] == " ":
                i += 1
            m = re.match(r"\"([^\"]*)\"|'([^']*)'|(\S+)", seg[i:])
            if m:
                targets.append(m.group(1) or m.group(2) or m.group(3))
            continue
        i += 1
    return targets


def check_segment(seg: str, reg: dict, branch=current_branch, state=collection_state):
    toks = tokens(seg)
    if not toks:
        return None
    g = git_parts(toks)
    if g:
        sub, args = g
        plain = [a for a in args if not a.startswith("-")]
        if sub == "push":
            if has_flag(args, "f", ("--force", "--force-with-lease")) or any(a.startswith("--force") for a in args) or any(a.startswith("+") for a in plain):
                return decision("deny", "Force-push is not allowed in this repository. Ask the user to do it themselves if it is truly needed.")
            refs = plain[1:] or [branch()]
            if any(r.split(":")[-1].removeprefix("refs/heads/") in MAIN_BRANCHES for r in refs):
                return decision("ask", "Pushing to main needs the user's explicit instruction. Push the feature branch and let the user merge.")
        if sub == "reset" and "--hard" in args:
            return decision("ask", "git reset --hard discards uncommitted work. Confirm with the user first.")
        if sub == "clean" and has_flag(args, "f", "--force") and not has_flag(args, "n", "--dry-run"):
            return decision("ask", "git clean -f deletes untracked files. Confirm with the user first.")
        if sub in ("checkout", "restore") and plain[-1:] == ["."] and "--staged" not in args:
            return decision("ask", f"git {sub} . discards all uncommitted changes. Confirm with the user first.")
        if sub == "commit":
            findings = commit_findings(args)
            if findings:
                return decision("deny", "Commit blocked: " + "; ".join(findings) + ". Fix the cause; do not bypass. A leaked key must be rotated.")
        return None
    if re.search(r"(^|[./])rag[./]ingest\b|(^|/)ingest\.py$", " ".join(toks)):
        target = ingest_target(toks)
        if target:
            name, url = target
            s = state(url, name)
            if s == "exists" and user_allows_destructive():
                return None
            if s != "missing":
                return decision(
                    "deny" if s == "exists" else "ask",  # an index cannot be restored; if Qdrant is unreachable the run would fail anyway
                    f"Ingestion DELETES and recreates collection {name} ({'it exists' if s == 'exists' else 'could not check whether it exists'}). "
                    "Use a new collection name for a new index. "
                    + (f"If the user really wants to recreate it, they must set {OVERRIDE_ENV}=1 before starting Claude Code." if s == "exists" else ""),
                )
        return None
    word = toks[0].lower()
    mutates = word in MUTATING or (word == "sed" and any(a.startswith("-i") or a == "--in-place" for a in toks[1:]))
    cands = protected_candidates(seg, reg)
    if cands:
        wrote = any(c in target for target in redirect_targets(seg) for c in cands)
        copies = word in ("cp", "copy", "install") and any(c in toks[-1].replace("\\", "/") for c in cands)
        if mutates or wrote or copies:
            return frozen_change(next((c for c in cands if is_irreversible(c)), cands[0]))
    return None


def check_bash(cmd: str, reg: dict, **kw):
    if not re.search(r"git|ingest|eval/|data/|eval\\|data\\", cmd):
        return None
    for seg in split_commands(cmd):
        d = check_segment(seg, reg, **kw)
        if d:
            return d
    return None


# ---------- hooks ----------


def pre_write(data: dict) -> dict | None:
    path = (data.get("tool_input") or {}).get("file_path") or ""
    r = rel(path) if path else None
    if r and is_protected(r, load_register()):
        return frozen_change(r)
    return None


def pre_bash(data: dict) -> dict | None:
    return check_bash((data.get("tool_input") or {}).get("command") or "", load_register())


def post_write(data: dict) -> int:
    path = (data.get("tool_input") or {}).get("file_path") or ""
    r = rel(path) if path else None
    py = project_python()
    if not r or not py:
        return 0
    if matches(r, PIN_TRIGGERS):
        args = ["tests/rag", "tests/evaluation/test_config.py", "-k", "fingerprint or differ"]
        label = "fingerprint / config-diff pin tests"
    elif matches(r, STUDIO_TRIGGERS):
        args = ["tests/ai_development"]
        label = "AI-development consistency tests"
    else:
        return 0
    if not all((ROOT / a).exists() for a in args if a.startswith("tests/")):
        return 0  # nothing to run yet (for example while the studio tests are being created)
    out = subprocess.run([py, "-m", "pytest", "-q", "-x", "--no-header", *args], cwd=ROOT, capture_output=True, text=True, timeout=85)
    if out.returncode in (0, 5):  # 5 = no tests collected: not a failure of the pins
        return 0
    tail = "\n".join((out.stdout + out.stderr).strip().splitlines()[-25:])
    sys.stderr.write(f"The {label} fail after editing {r}. Fix before continuing:\n{tail}\n")
    return 2


def cli_verify() -> int:
    rows = verify(load_register())
    for status, name, detail in rows:
        print(f"{status:<8} {name}" + (f"  ({detail})" if detail else ""))
    bad = sum(1 for s, _, _ in rows if s == "MISMATCH")
    print(f"frozen artifacts: {sum(1 for s, _, _ in rows if s == 'OK')} OK, {bad} MISMATCH, {sum(1 for s, _, _ in rows if s == 'SKIPPED')} SKIPPED")
    return 1 if bad else 0


def main(argv: list[str]) -> int:
    action = argv[1] if len(argv) > 1 else ""
    try:
        if action == "verify":
            return cli_verify()
        try:
            data = json.load(sys.stdin)
        except Exception:
            data = {}
        if action == "post-write":
            return post_write(data)
        result = pre_write(data) if action == "pre-write" else pre_bash(data) if action == "pre-bash" else None
        if result:
            print(json.dumps(result))
        return 0
    except Exception as exc:  # fail open: a bug here must never stop work
        sys.stderr.write(f"guard.py ignored an internal error: {type(exc).__name__}: {exc}\n")
        return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
