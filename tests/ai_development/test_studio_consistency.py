"""Static consistency of the AI-development layer: AGENTS.md, CLAUDE.md, skills, agents, rules, hooks, docs.

Offline and deterministic: these tests only read files. They exist to stop drift: broken links, stale
commands, a skill that is never routed, an agent that gained write tools, a rule that matches nothing.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SKILLS = sorted((ROOT / ".claude" / "skills").glob("*/SKILL.md"))
AGENTS = sorted((ROOT / ".claude" / "agents").glob("*.md"))
RULES = sorted((ROOT / ".claude" / "rules").glob("*.md"))
DOCS = sorted((ROOT / "docs" / "ai-development").glob("*.md"))
TOP = [ROOT / "AGENTS.md", ROOT / "CLAUDE.md"]
ALL_TEXT = [*TOP, *DOCS, *SKILLS, *AGENTS, *RULES]

SKILL_SECTIONS = ["## Purpose", "## When to use", "## Inputs", "## Workflow", "## Required checks", "## Output", "## STOP"]
AGENT_SECTIONS = ["## Purpose", "## Procedure", "## Output", "## STOP"]
KNOWN_TOOLS = {"Read", "Grep", "Glob", "Bash", "WebFetch", "WebSearch"}
HOOK_ACTIONS = {"pre-write", "pre-bash", "post-write", "verify", "scan-staged"}
RUNNER_FLAGS = {
    "--defer-judge": "eval/runners/run_eval.py",
    "--no-judge": "eval/runners/resume_eval.py",
    "--experiments": "eval/runners/benchmark.py",
    "--baseline": "eval/runners/benchmark.py",
    "--all": "eval/runners/benchmark.py",
}
# backticked tokens that look like paths but are intentionally not repository files
# docs that describe another repository by file name; their backticked names are not paths in this repo
EXTERNAL_REFERENCE_DOCS = {"STUDIO_REUSE_AUDIT.md"}
NOT_PATHS = {".env", "experiments", "common", "summary.json", "manifest.json", "config.yaml", "items.jsonl", "golden.json", "SKILL.md"}
KEY_SHAPE = re.compile(rb"(?<![A-Za-z0-9])(?:AIza[0-9A-Za-z_-]{20,}|gsk_[0-9A-Za-z]{20,}|nvapi-[0-9A-Za-z_-]{20,}|sk-[0-9A-Za-z_-]{20,})")


def split_frontmatter(path: Path) -> tuple[dict, str]:
    text = path.read_text(encoding="utf-8")
    m = re.match(r"---\n(.*?)\n---\n(.*)", text, re.S)
    assert m, f"{path.name}: no frontmatter starting on line 1"
    return yaml.safe_load(m.group(1)), m.group(2)


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def project_file_names() -> set[str]:
    """Names of every file in the project's own folders (not .venv or .git), for bare-name references."""
    names = {p.name for p in ROOT.iterdir()}
    for folder in ("src", "tests", "eval", "docs", ".claude", "data"):
        names |= {p.name for p in (ROOT / folder).rglob("*")}
    return names


def test_the_layer_exists():
    assert len(SKILLS) >= 11 and len(AGENTS) >= 5 and len(RULES) >= 5 and len(DOCS) >= 5
    assert all(p.exists() for p in TOP)


@pytest.mark.parametrize("path", SKILLS, ids=lambda p: p.parent.name)
def test_skill_is_well_formed(path):
    meta, body = split_frontmatter(path)
    assert set(meta) == {"name", "description"}, f"unexpected frontmatter keys {sorted(meta)}"
    assert meta["name"] == path.parent.name
    assert 60 <= len(meta["description"]) <= 600
    for heading in SKILL_SECTIONS:
        assert heading in body, f"missing {heading}"
    assert len(path.read_text(encoding="utf-8").splitlines()) <= 100


@pytest.mark.parametrize("path", AGENTS, ids=lambda p: p.stem)
def test_agent_is_well_formed_and_read_only(path):
    meta, body = split_frontmatter(path)
    assert meta["name"] == path.stem
    assert 60 <= len(meta["description"]) <= 600
    tools = {t.strip() for t in str(meta["tools"]).split(",")}
    assert tools <= KNOWN_TOOLS, f"unknown tools {sorted(tools - KNOWN_TOOLS)}"
    assert not tools & {"Write", "Edit", "NotebookEdit"}, "agents are read-only; the main conversation edits"
    skills = meta.get("skills") or []
    assert skills, "an agent preloads the skills its procedure uses"
    for skill in skills:
        assert (ROOT / ".claude" / "skills" / skill / "SKILL.md").exists(), f"unknown skill {skill}"
    for heading in AGENT_SECTIONS:
        assert heading in body, f"missing {heading}"
    assert len(path.read_text(encoding="utf-8").splitlines()) <= 80


@pytest.mark.parametrize("path", RULES, ids=lambda p: p.stem)
def test_rule_paths_match_real_files(path):
    meta, body = split_frontmatter(path)
    assert set(meta) == {"paths"}, "paths is the only field Claude Code reads in a rule"
    for pattern in meta["paths"]:
        assert list(ROOT.glob(pattern)), f"{rel(path)}: pattern {pattern!r} matches nothing"
    assert len(path.read_text(encoding="utf-8").splitlines()) <= 40


def test_every_skill_is_routed_from_agents_md_and_every_agent_from_claude_md():
    agents_md = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    claude_md = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    assert [s.parent.name for s in SKILLS if f"`{s.parent.name}`" not in agents_md] == []
    assert [a.stem for a in AGENTS if f"`{a.stem}`" not in claude_md] == []


def test_always_loaded_context_stays_small_and_claude_md_imports_agents_md():
    lines = sum(len(p.read_text(encoding="utf-8").splitlines()) for p in TOP)
    assert lines < 200, f"AGENTS.md + CLAUDE.md = {lines} lines (guidance: under 200 per file; the pair is loaded together)"
    assert (ROOT / "CLAUDE.md").read_text(encoding="utf-8").startswith("@AGENTS.md")


def test_markdown_links_and_backticked_paths_exist():
    problems = []
    names = project_file_names()
    for path in ALL_TEXT:
        text = path.read_text(encoding="utf-8")
        for target in re.findall(r"\]\(([^)#\s]+)\)", text):
            if not target.startswith("http") and not (path.parent / target).resolve().exists():
                problems.append(f"{rel(path)}: broken link {target}")
        if path.name in EXTERNAL_REFERENCE_DOCS:
            continue
        for ref in set(re.findall(r"`([A-Za-z0-9_./-]+\.[a-z]{2,5}|[A-Za-z0-9_./-]+/)`", text)):
            if re.search(r"[<>*{}\[\]]|NN|\.\.\.|…", ref) or ref.startswith((".venv/", ".git/", "localhost", "http")) or ref.rstrip("/") in NOT_PATHS:
                continue
            cand = ref.rstrip("/")
            if "/" not in cand and cand in names:
                continue  # bare file name used as shorthand, for example `resume_eval.py`
            if not (ROOT / cand).exists() and not (ROOT / "src" / "archagenticrag" / cand).exists():
                problems.append(f"{rel(path)}: path not found `{ref}`")
    assert problems == []


def test_quoted_commands_flags_and_hook_actions_exist():
    problems = []
    for flag, script in RUNNER_FLAGS.items():
        if flag not in (ROOT / script).read_text(encoding="utf-8"):
            problems.append(f"{flag} is not in {script}")
    guard = (ROOT / ".claude" / "hooks" / "guard.py").read_text(encoding="utf-8")
    for path in ALL_TEXT:
        text = path.read_text(encoding="utf-8")
        # an action is named only in a command (`python ... guard.py verify`) or as `guard.py verify` in backticks
        for action in [*re.findall(r"python\s+\S*guard\.py[\"']?\s+([a-z-]+)", text), *re.findall(r"`guard\.py\s+([a-z-]+)`", text)]:
            if action not in HOOK_ACTIONS or f'"{action}"' not in guard and f"'{action}'" not in guard:
                problems.append(f"{rel(path)}: unknown guard.py action {action!r}")
        for script in re.findall(r"eval/runners/([a-z_]+\.py)", text):
            if not (ROOT / "eval" / "runners" / script).exists():
                problems.append(f"{rel(path)}: runner {script} does not exist")
    assert problems == []


def test_no_rule_line_is_duplicated_across_files():
    seen: dict[str, str] = {}
    duplicates = []
    for path in ALL_TEXT:
        for line in path.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if len(s) >= 90 and not s.startswith(("|", "```", "http")):
                if seen.setdefault(s, rel(path)) != rel(path):
                    duplicates.append(f"{seen[s]} and {rel(path)}: {s[:60]}")
    assert duplicates == []


def test_text_hygiene_lf_only_and_no_key_shaped_content():
    own_tests = sorted((ROOT / "tests" / "ai_development").glob("*.py"))  # test data must be assembled at runtime, not written out
    for path in [*ALL_TEXT, *own_tests, ROOT / ".claude" / "settings.json", ROOT / ".claude" / "hooks" / "guard.py"]:
        data = path.read_bytes()
        assert b"\r\n" not in data, f"{rel(path)} has CRLF line endings"
        assert not KEY_SHAPE.search(data), f"{rel(path)} contains key-shaped text"


def test_settings_wire_only_known_hooks_to_the_guard_script():
    settings = json.loads((ROOT / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert set(settings) == {"hooks"}, "settings.json carries hooks only"
    assert set(settings["hooks"]) == {"PreToolUse", "PostToolUse"}
    seen_actions = set()
    for event, entries in settings["hooks"].items():
        for entry in entries:
            assert entry["matcher"] in {"Write|Edit", "Bash|PowerShell"}
            for hook in entry["hooks"]:
                assert hook["type"] == "command" and hook["timeout"] >= 10
                m = re.fullmatch(r'python "\$CLAUDE_PROJECT_DIR/\.claude/hooks/guard\.py" ([a-z-]+)', hook["command"])
                assert m and m.group(1) in HOOK_ACTIONS, hook["command"]
                seen_actions.add(m.group(1))
    assert seen_actions == {"pre-write", "pre-bash", "post-write"}
    assert (ROOT / ".claude" / "hooks" / "guard.py").exists()


def test_frozen_register_is_well_formed_and_matches_the_files_present():
    reg = json.loads((ROOT / "docs" / "ai-development" / "frozen-artifacts.json").read_text(encoding="utf-8"))
    assert {"protected_globs", "files", "fingerprints", "verified_on"} <= set(reg)
    mismatched = []
    for name, expected in reg["files"].items():
        f = ROOT / name
        if not f.exists():
            assert name.startswith("eval/results/"), f"tracked frozen file missing: {name}"
            continue  # run results are gitignored: absent on a fresh clone
        if hashlib.sha256(f.read_bytes()).hexdigest() != expected:
            mismatched.append(name)
    assert mismatched == [], f"frozen artifact changed: {mismatched}"
    from archagenticrag.evaluation.config import load_config

    for name, expected in reg["fingerprints"].items():
        assert load_config(ROOT / name).fingerprint() == expected, f"fingerprint changed: {name}"
