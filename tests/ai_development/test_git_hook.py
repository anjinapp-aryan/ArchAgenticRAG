"""The versioned pre-commit hook (.githooks/pre-commit), exercised in disposable repositories.

Each test builds a throw-away repository in a temp folder, installs the hook the way the README says
(core.hooksPath) and makes real `git commit` calls. The real repository is never touched. Keys are synthetic.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from .test_secret_scanning import SHAPELESS, TOKENS

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(shutil.which("git") is None or shutil.which("sh") is None, reason="needs git and sh")


def git(repo: Path, *args: str, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)


@pytest.fixture
def repo(tmp_path) -> Path:
    r = tmp_path / "repo"
    (r / ".githooks").mkdir(parents=True)
    (r / ".claude" / "hooks").mkdir(parents=True)
    shutil.copy2(ROOT / ".githooks" / "pre-commit", r / ".githooks" / "pre-commit")
    shutil.copy2(ROOT / ".claude" / "hooks" / "guard.py", r / ".claude" / "hooks" / "guard.py")
    os.chmod(r / ".githooks" / "pre-commit", 0o755)
    git(r, "init", "-q")
    git(r, "config", "user.email", "test@example.com")
    git(r, "config", "user.name", "Test")
    git(r, "config", "core.hooksPath", ".githooks")  # the documented install command
    return r


def commit(repo: Path, message: str = "test", env: dict | None = None) -> subprocess.CompletedProcess:
    return git(repo, "commit", "-q", "-m", message, env=env)


def test_a_clean_commit_passes(repo):
    (repo / "notes.md").write_text("nothing secret here\n", encoding="utf-8")
    git(repo, "add", "notes.md")
    assert commit(repo).returncode == 0


@pytest.mark.parametrize("name", ["OpenAI project", "Anthropic", "OpenRouter", "SambaNova (variable)", "Cloudflare token (variable)", "GitHub token", "Private key"])
def test_a_staged_secret_blocks_the_commit_and_is_not_echoed(repo, name):
    label, line = TOKENS[name]
    (repo / "config.txt").write_text(line + "\n", encoding="utf-8")
    git(repo, "add", "config.txt")
    result = commit(repo)
    assert result.returncode != 0
    assert label in result.stderr and "config.txt" in result.stderr
    value = line.split("=", 1)[-1].strip() if "=" in line else line.split()[-1]
    assert value not in result.stderr + result.stdout, "the hook repeated the secret"
    assert git(repo, "log", "--oneline").returncode != 0 or git(repo, "log", "--oneline").stdout.strip() == ""  # nothing was committed


def test_an_env_file_is_blocked_but_the_example_is_allowed(repo):
    (repo / ".env.example").write_text("GROQ_API_KEY=\nSAMBANOVA_API_KEY=your-key-here\nCLOUDFLARE_ACCOUNT_ID=\n", encoding="utf-8")
    git(repo, "add", ".env.example")
    assert commit(repo).returncode == 0
    (repo / ".env").write_text("FOO=bar\n", encoding="utf-8")
    git(repo, "add", "-f", ".env")
    blocked = commit(repo, "second")
    assert blocked.returncode != 0 and ".env is an environment file" in blocked.stderr


def test_a_value_from_the_local_env_file_is_blocked_whatever_its_shape(repo):
    (repo / ".env").write_text("PROVIDER_API_KEY=" + SHAPELESS + "\n", encoding="utf-8")
    (repo / "page.md").write_text("see " + SHAPELESS + "\n", encoding="utf-8")
    git(repo, "add", "page.md")  # .env itself stays unstaged
    result = commit(repo)
    assert result.returncode != 0 and "value of PROVIDER_API_KEY from .env appears in page.md" in result.stderr
    assert SHAPELESS not in result.stderr


def test_it_fails_closed_when_the_scanner_itself_breaks(repo):
    (repo / ".claude" / "hooks" / "guard.py").write_text("raise SystemExit(7)\n", encoding="utf-8")
    (repo / "notes.md").write_text("harmless\n", encoding="utf-8")
    git(repo, "add", "notes.md")
    assert commit(repo).returncode != 0


def test_it_fails_closed_when_python_cannot_be_found(repo):
    minimal = os.pathsep.join(dict.fromkeys(str(Path(shutil.which(tool)).parent) for tool in ("git", "sh")))
    if shutil.which("python3", path=minimal) or shutil.which("python", path=minimal):
        pytest.skip("Python lives in the same folder as git or sh on this machine, so it cannot be hidden")
    (repo / "notes.md").write_text("harmless\n", encoding="utf-8")
    git(repo, "add", "notes.md")
    result = commit(repo, env={**os.environ, "PATH": minimal})
    assert result.returncode != 0 and "Python 3 was not found" in result.stderr


def test_scan_staged_runs_with_the_interpreter_running_the_tests(repo):
    """The command the hook ends in, run directly: exit 0 when clean, 1 when a secret is staged."""
    guard_py = repo / ".claude" / "hooks" / "guard.py"
    (repo / "a.md").write_text("fine\n", encoding="utf-8")
    git(repo, "add", "a.md")
    assert subprocess.run([sys.executable, str(guard_py), "scan-staged"], cwd=repo).returncode == 0
    (repo / "b.md").write_text(TOKENS["Groq"][1] + "\n", encoding="utf-8")
    git(repo, "add", "b.md")
    assert subprocess.run([sys.executable, str(guard_py), "scan-staged"], cwd=repo, capture_output=True).returncode == 1


def test_a_diff_with_any_unicode_does_not_crash_the_scan(repo):
    (repo / "u.md").write_text("arrows → and — dashes ≠ and emoji \U0001f600 and \u0081\u008d\n", encoding="utf-8")
    git(repo, "add", "u.md")
    assert commit(repo).returncode == 0


def test_the_committed_hook_is_executable_and_lf_only():
    hook = ROOT / ".githooks" / "pre-commit"
    assert b"\r\n" not in hook.read_bytes(), "a CRLF shebang line breaks the hook on Linux"
    entry = subprocess.run(["git", "ls-files", "-s", ".githooks/pre-commit"], cwd=ROOT, capture_output=True, text=True).stdout.split()
    if not entry:
        pytest.skip("the hook is not tracked yet; after adding it run: git update-index --chmod=+x .githooks/pre-commit")
    assert entry[0] == "100755", "the tracked hook must carry the executable bit for Linux"
