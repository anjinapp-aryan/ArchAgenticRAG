"""Behaviour of .claude/hooks/guard.py. Offline: no git state, no Qdrant and no network are used;
git, Qdrant and the commit scan are injected or monkeypatched."""

from __future__ import annotations

import importlib.util
import io
import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("studio_guard", ROOT / ".claude" / "hooks" / "guard.py")
guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(guard)

REG = {
    "protected_globs": ["eval/results", "eval/results/*", "eval/datasets/*/golden.json", "eval/datasets/*/qrels/*", "data/corpus", "data/corpus/*"],
    "files": {},
    "fingerprints": {"eval/configs/baseline-basic-rag.yaml": "x"},
}


def kind(result):
    return result["hookSpecificOutput"]["permissionDecision"] if result else None


def check(cmd, *, branch="feat/x", state="exists", findings=()):
    guard_commit = guard.commit_findings
    guard.commit_findings = lambda args: list(findings)
    try:
        return kind(guard.check_bash(cmd, REG, branch=lambda: branch, state=lambda url, name: state))
    finally:
        guard.commit_findings = guard_commit


# ---- write guard ----


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("eval/configs/baseline-basic-rag.yaml", "ask"),
        ("eval/datasets/peps-v1/golden.json", "ask"),
        ("eval/datasets/peps-v1/qrels/anything.json", "ask"),
        ("eval/results/20261001T173531Z-x/items.jsonl", "deny"),  # irreversible: gitignored evidence
        ("data/corpus/peps/pep-0008.rst", "ask"),
        ("eval/configs/exp04-new-experiment.yaml", None),  # a new config is not frozen
        ("src/archagenticrag/rag/rerank.py", None),
        ("docs/EXPERIMENT-03-RERANKING.md", None),
        ("eval/experiments.yaml", None),
    ],
)
def test_write_guard(path, expected, monkeypatch):
    monkeypatch.setattr(guard, "load_register", lambda: REG)
    assert kind(guard.pre_write({"tool_input": {"file_path": str(ROOT / path)}})) == expected


def test_write_guard_denies_results_unless_the_user_unlocked_them(monkeypatch):
    monkeypatch.setattr(guard, "load_register", lambda: REG)
    target = {"tool_input": {"file_path": str(ROOT / "eval/results/x/items.jsonl")}}
    assert kind(guard.pre_write(target)) == "deny"
    monkeypatch.setenv(guard.OVERRIDE_ENV, "1")
    assert guard.pre_write(target) is None


def test_write_guard_ignores_files_outside_the_project_and_bad_input(monkeypatch):
    monkeypatch.setattr(guard, "load_register", lambda: REG)
    assert guard.pre_write({"tool_input": {"file_path": str(Path.home() / "notes.txt")}}) is None
    assert guard.pre_write({}) is None


# ---- command guard: must be flagged ----


@pytest.mark.parametrize(
    ("cmd", "expected"),
    [
        ("git push --force origin feat/x", "deny"),
        ("git push -f", "deny"),
        ("git push origin +feat/x", "deny"),
        ("git push --force-with-lease origin feat/x", "deny"),
        ("git -C . push -uf origin feat/x", "deny"),
        ("git push origin main", "ask"),
        ("git push origin HEAD:main", "ask"),
        ("git reset --hard HEAD~1", "ask"),
        ("git clean -fd", "ask"),
        ("git checkout .", "ask"),
        ("git restore .", "ask"),
        ("python -m archagenticrag.rag.ingest eval/configs/baseline-basic-rag.yaml", "deny"),  # recreates an existing index
        ("rm -rf eval/results/20261001T173531Z-baseline", "deny"),
        ("rm eval/datasets/peps-v1/golden.json", "ask"),
        ("sed -i 's/a/b/' eval/datasets/peps-v1/golden.json", "ask"),
        ("echo x > eval/results/foo/items.jsonl", "deny"),
        ("cp /tmp/x.json eval/datasets/peps-v1/qrels/new.json", "ask"),
        ("Remove-Item -Recurse eval\\results\\old", "deny"),
        ("git add -A && git commit -m x && git push --force", "deny"),
    ],
)
def test_command_guard_flags(cmd, expected):
    assert check(cmd) == expected


def test_push_without_a_target_uses_the_current_branch():
    assert check("git push", branch="main") == "ask"
    assert check("git push", branch="feat/x") is None
    assert check("git push -u origin", branch="main") == "ask"


def test_the_irreversible_cases_have_a_human_only_override(monkeypatch):
    cmd = "python -m archagenticrag.rag.ingest eval/configs/baseline-basic-rag.yaml"
    assert check(cmd) == "deny" and check("rm -rf eval/results/x") == "deny"
    monkeypatch.setenv(guard.OVERRIDE_ENV, "1")  # what the user sets before starting Claude Code
    assert check(cmd) is None and check("rm -rf eval/results/x") is None
    assert check("rm eval/datasets/peps-v1/golden.json") == "ask"  # recoverable from git: still confirmed, not unlocked
    monkeypatch.setenv(guard.OVERRIDE_ENV, "yes")  # only the exact value 1 unlocks
    assert check("rm -rf eval/results/x") == "deny"


def test_ingest_into_a_new_collection_is_allowed():
    cmd = "python -m archagenticrag.rag.ingest eval/configs/baseline-basic-rag.yaml"
    assert check(cmd, state="missing") is None
    assert check(cmd, state="unknown") == "ask"  # cannot prove the collection is new


# ---- command guard: must NOT be flagged (routine work) ----


@pytest.mark.parametrize(
    "cmd",
    [
        "git status -sb",
        "git push -u origin feat/experiment-lab-hybrid-fallback",
        "git push origin feat/x",
        "git log -5 --oneline",
        "git diff --stat",
        "git clean -n",
        "git clean -nd",
        "git checkout -b feat/new",
        "git restore --staged .",
        "git checkout main",
        "ls eval/results && sha256sum eval/datasets/peps-v1/golden.json",
        "cat eval/results/20261001T173531Z-baseline/summary.json",
        "grep -r PASS eval/results | head",
        ".venv/Scripts/python eval/runners/benchmark.py --all",
        ".venv/Scripts/python eval/runners/run_eval.py eval/configs/exp03-hybrid-rerank.yaml --defer-judge",
        ".venv/Scripts/python eval/runners/resume_eval.py eval/results/20261027T180058Z-x --no-judge",
        ".venv/Scripts/python -m pytest -m integration -q",
        "rm -f /tmp/scratch.py",
        "rm -rf .pytest_cache",
        "cp eval/configs/baseline-basic-rag.yaml eval/configs/exp04-new.yaml",
        'git commit -m "docs: explain git push --force and rm -rf eval/results and git reset --hard"',
        "git commit -F - <<'EOF'\nfeat: x\n\nrm -rf eval/results; git push --force; git reset --hard\nEOF",
        "python - <<'PY'\nimport shutil\nshutil.rmtree('eval/results/x')\nPY",  # heredoc bodies are code, not commands
        "echo 'git push --force' > /tmp/notes.txt",
        "curl -s localhost:6333/collections/peps_v1_bge_small_docling_480",
    ],
)
def test_command_guard_leaves_routine_commands_alone(cmd):
    assert check(cmd) is None


# ---- commit gate ----


def test_commit_is_denied_on_a_finding_and_allowed_when_clean():
    assert check("git commit -m x", findings=["value of GROQ_API_KEY from .env appears in a.py"]) == "deny"
    assert check("git commit -am x", findings=["frozen artifact changed: eval/datasets/peps-v1/golden.json"]) == "deny"
    assert check("git commit -m x", findings=[]) is None


def test_commit_flags_decide_which_diff_is_scanned(monkeypatch):
    seen = []
    monkeypatch.setattr(guard, "git", lambda *a, **k: seen.append(a) or "")
    monkeypatch.setattr(guard, "checkpoint_test_failures", lambda names: [])
    monkeypatch.setattr(guard, "env_secrets", lambda: {})
    monkeypatch.setattr(guard, "verify", lambda reg: [])
    monkeypatch.setattr(guard, "load_register", lambda: REG)
    def diff_scanned(args):
        seen.clear()
        guard.commit_findings(args)
        assert len({call[:2] for call in seen}) == 1, "one commit must scan one consistent diff"
        return seen[0][:2]

    assert diff_scanned(["-m", "msg"]) == ("diff", "--cached")
    assert diff_scanned(["-am", "msg"]) == ("diff", "HEAD")
    assert diff_scanned(["--all", "-m", "msg"]) == ("diff", "HEAD")


# ---- secret scan: names and files only, never values ----

FAKE_VALUE = "zz-synthetic-not-a-real-key-9f3a1c7e"
# Key-shaped test data is assembled at runtime: written out in full, these lines would make this very file
# trip the commit gate and the git pre-commit hook. None of them is a real credential.
FAKE_OPENROUTER_SHAPE = "sk-" + "or-v1-" + "0123456789abcdef" * 3
FAKE_GROQ_SHAPE = "gsk" + "_" + "FAKEFAKEFAKEFAKEFAKEFAKE0123456789"


def test_scan_finds_env_values_and_key_shapes_without_echoing_them():
    diff = "\n".join(
        [
            "+++ b/src/a.py",
            f'+note = "{FAKE_VALUE}"',
            "+++ b/docs/b.md",
            f"+key {FAKE_OPENROUTER_SHAPE}",
            "+++ b/c.txt",
            f"+{FAKE_GROQ_SHAPE}",
        ]
    )
    findings = guard.scan_diff(diff, {"FAKE_PROVIDER_API_KEY": FAKE_VALUE})
    assert findings == [
        "Groq key appears in c.txt",
        "OpenRouter key appears in docs/b.md",
        "value of FAKE_PROVIDER_API_KEY from .env appears in src/a.py",
    ]
    assert all(FAKE_VALUE not in f and "0123456789abcdef" not in f for f in findings)


@pytest.mark.parametrize(
    "line",
    [
        "+a task-based-evaluation-run-with-many-parts",  # "sk-" inside a word
        "+risk-assessment-framework-for-evaluation-runs",
        "+GROQ_API_KEY=",  # placeholder, as in .env.example
        "+see https://openrouter.ai/api/v1",
    ],
)
def test_scan_does_not_flag_ordinary_text(line):
    assert guard.scan_diff("+++ b/x.md\n" + line, {}) == []


def test_env_secrets_reads_only_secret_looking_long_values(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text(f"GROQ_API_KEY={FAKE_VALUE}\nRAGAS_DO_NOT_TRACK=true\nSHORT_TOKEN=abc\nLANGFUSE_HOST=http://localhost:3000\n", encoding="utf-8")
    monkeypatch.setattr(guard, "ENV_FILE", env)
    assert guard.env_secrets() == {"GROQ_API_KEY": FAKE_VALUE}


# ---- command splitting ----


def test_a_backslash_newline_continues_the_command_instead_of_splitting_it():
    cmd = "sed -e 's/a/b/' \
  -e 's/c/d/' \
  eval/configs/baseline-basic-rag.yaml > eval/configs/exp04-new.yaml"
    assert len(guard.split_commands(cmd)) == 1
    assert check(cmd) is None  # reads the frozen config, writes a new one
    assert check(cmd.replace("> eval/configs/exp04-new.yaml", "> eval/configs/baseline-basic-rag.yaml")) == "ask"  # writes a frozen config


def test_redirect_detection_ignores_arrows_in_quotes_and_fd_duplication():
    assert guard.redirect_targets("echo hi > eval/results/x.txt") == ["eval/results/x.txt"]
    assert guard.redirect_targets('echo hi >> "eval/results/x.txt" 2>&1') == ["eval/results/x.txt"]
    assert guard.redirect_targets("sed -e 's/retrieve -> generate/x/' in.yaml") == []
    assert guard.redirect_targets("python run.py 2>&1") == []
    sed = "sed -e 's/retrieve -> generate/x/' eval/configs/baseline-basic-rag.yaml > eval/configs/baseline-basic-rag.yaml"
    assert check(sed) == "ask"  # the quoted '->' must not hide the real redirect
    assert check("echo 'a -> b' && ls eval/results") is None


def test_split_commands_respects_quotes_and_drops_heredoc_bodies():
    assert guard.split_commands('echo "a; b" && git status | cat') == ['echo "a; b"', "git status", "cat"]
    assert guard.split_commands("cat <<'EOF'\nrm -rf eval/results\nEOF\nls") == ["cat", "ls"]


# ---- PostToolUse feedback contract ----


class Done:
    def __init__(self, rc, out=""):
        self.returncode, self.stdout, self.stderr = rc, out, ""


def test_post_write_runs_the_pin_tests_for_config_edits_and_reports_failure(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(guard, "project_python", lambda: "python")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: calls.append(a[0]) or Done(1, "FAILED test_baseline_config_fingerprint_is_unchanged"))
    assert guard.post_write({"tool_input": {"file_path": str(ROOT / "eval/configs/exp03-hybrid-rerank.yaml")}}) == 2
    assert "-k" in calls[0] and "fingerprint or differ" in calls[0]
    assert "fingerprint" in capsys.readouterr().err


def test_post_write_runs_only_the_lint_test_of_the_edited_skill_and_passes_quietly(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(guard, "project_python", lambda: "python")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: calls.append(a[0]) or Done(0))
    assert guard.post_write({"tool_input": {"file_path": str(ROOT / ".claude/skills/testing/SKILL.md")}}) == 0
    assert len(calls) == 1 and calls[0][-1] == "tests/ai_development/test_studio_consistency.py::test_skill_is_well_formed[testing]"
    assert "tests/ai_development" not in calls[0][:-1], "the whole studio suite must wait for the checkpoint"
    assert capsys.readouterr().err == ""


def test_post_write_ignores_other_files_and_treats_no_tests_collected_as_success(monkeypatch):
    monkeypatch.setattr(guard, "project_python", lambda: "python")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("must not run"))
    assert guard.post_write({"tool_input": {"file_path": str(ROOT / "docs/EXPERIMENT-03-RERANKING.md")}}) == 0
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: Done(5))
    assert guard.post_write({"tool_input": {"file_path": str(ROOT / "AGENTS.md")}}) == 0


# ---- fail open ----


def test_main_fails_open_on_garbage_input_and_internal_errors(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO("this is not json"))
    assert guard.main(["guard.py", "pre-bash"]) == 0
    monkeypatch.setattr(guard, "pre_bash", lambda data: 1 / 0)
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"tool_input": {"command": "git status"}})))
    assert guard.main(["guard.py", "pre-bash"]) == 0
    assert "ignored an internal error" in capsys.readouterr().err
    assert guard.main(["guard.py", "unknown-action"]) == 0


def test_verify_is_clean_on_this_checkout():
    rows = guard.verify(guard.load_register())
    assert [r for r in rows if r[0] == "MISMATCH"] == []
    assert any(r[0] == "OK" for r in rows)


# ---- two-tier drift checks: tier 1 after each edit, tier 2 at the commit checkpoint ----


@pytest.fixture
def studio(tmp_path, monkeypatch):
    """A scratch project root, so the tier-1 checks read real files without touching the repository."""
    for sub in ("docs/ai-development", ".claude/hooks", ".claude/skills/demo", "tests/ai_development"):
        (tmp_path / sub).mkdir(parents=True)
    monkeypatch.setattr(guard, "ROOT", tmp_path)
    monkeypatch.setattr(guard, "project_python", lambda: "python")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("tier 1 must not start pytest for this edit"))

    def edit(rel_path: str, content: bytes | str):
        p = tmp_path / rel_path
        p.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
        return guard.post_write({"tool_input": {"file_path": str(p)}})

    return edit


def test_tier1_stays_silent_for_an_unrouted_or_half_finished_cross_file_state(studio, monkeypatch):
    # a docs edit that mentions a file which does not exist yet: a cross-file problem, reported at the checkpoint, not now
    assert studio("docs/ai-development/NOTES.md", "See `eval/runners/not_written_yet.py` and [link](MISSING.md).\n") == 0


def test_tier1_reports_problems_the_edited_file_has_on_its_own(studio, capsys):
    assert studio("docs/ai-development/CRLF.md", b"line one\r\nline two\r\n") == 2
    assert "CRLF" in capsys.readouterr().err
    assert studio(".claude/hooks/broken.py", "def f(:\n") == 2
    assert "syntax error at line 1" in capsys.readouterr().err
    assert studio(".claude/settings.json", "{not json") == 2
    assert "not valid JSON" in capsys.readouterr().err


def test_tier1_reports_key_shaped_text_by_label_not_value(studio, capsys):
    from .test_secret_scanning import TOKENS

    line = TOKENS["Groq"][1]
    assert studio("docs/ai-development/LEAK.md", line + "\n") == 2
    err = capsys.readouterr().err
    assert "Groq key" in err and line.split()[-1] not in err


def test_tier1_runs_one_pytest_node_for_a_malformed_skill_and_reports_it(studio, monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: calls.append(a[0]) or Done(1, "FAILED tests/ai_development/test_studio_consistency.py::test_skill_is_well_formed[demo] - AssertionError: missing ## STOP"))
    assert studio(".claude/skills/demo/SKILL.md", "---\nname: demo\n---\n") == 2
    assert len(calls) == 1 and calls[0][-1].endswith("test_skill_is_well_formed[demo]")
    assert "missing ## STOP" in capsys.readouterr().err  # tier-1 feedback shows the test output so the author can fix it


def test_checkpoint_runs_the_cross_file_tests_once_and_reports_test_ids_only(monkeypatch):
    calls = []
    monkeypatch.setattr(guard, "project_python", lambda: "python")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: calls.append(a[0]) or Done(1, "FAILED tests/ai_development/test_studio_consistency.py::test_every_skill_is_routed - AssertionError: ['zz-new'] a secret-looking message"))
    findings = guard.checkpoint_test_failures(["AGENTS.md", ".claude/skills/zz-new/SKILL.md", "docs/ai-development/X.md"])
    assert len(calls) == 1 and "tests/ai_development" in calls[0]
    assert findings == ["AI-development tests fail: tests/ai_development/test_studio_consistency.py::test_every_skill_is_routed"]
    assert "secret-looking" not in findings[0]


def test_checkpoint_runs_the_pin_tests_for_config_changes_and_nothing_for_other_files(monkeypatch):
    calls = []
    monkeypatch.setattr(guard, "project_python", lambda: "python")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: calls.append(a[0]) or Done(0))
    assert guard.checkpoint_test_failures(["eval/configs/exp04-new.yaml"]) == []
    assert len(calls) == 1 and "fingerprint or differ" in calls[0]
    calls.clear()
    assert guard.checkpoint_test_failures(["src/archagenticrag/rag/rerank.py", "README.md"]) == []
    assert calls == []


def test_the_commit_gate_includes_the_checkpoint_tests(monkeypatch):
    monkeypatch.setattr(guard, "secret_findings", lambda base, strict=False: [])
    monkeypatch.setattr(guard, "verify", lambda reg: [])
    monkeypatch.setattr(guard, "load_register", lambda: REG)
    monkeypatch.setattr(guard, "git", lambda *a, **k: "AGENTS.md\n")
    monkeypatch.setattr(guard, "checkpoint_test_failures", lambda names: ["AI-development tests fail: x"] if "AGENTS.md" in names else [])
    assert guard.commit_findings(["-m", "msg"]) == ["AI-development tests fail: x"]


def test_a_pytest_timeout_at_the_commit_gate_is_reported_not_swallowed(monkeypatch):
    """A slow suite must not turn into a silent pass (or a fail-open that drops the secret findings)."""
    monkeypatch.setattr(guard, "project_python", lambda: "python")

    def slow(args, timeout=85):
        raise subprocess.TimeoutExpired(cmd="pytest", timeout=timeout)

    monkeypatch.setattr(guard, "run_pytest", slow)
    findings = guard.checkpoint_test_failures(["AGENTS.md", "eval/configs/exp04-new.yaml"])
    assert len(findings) == 2 and all("did not finish in time" in f for f in findings)
