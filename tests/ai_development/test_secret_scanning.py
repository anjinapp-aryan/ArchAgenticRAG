"""Secret detection: every provider format, harmless text, placeholders, redaction, and the repository itself.

All keys here are random synthetic strings assembled at runtime, so this file contains no key-shaped literal.
Nothing real is used and nothing is printed.
"""

from __future__ import annotations

import importlib.util
import random
import string
import subprocess
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("studio_guard", ROOT / ".claude" / "hooks" / "guard.py")
guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(guard)

ALNUM = string.ascii_letters + string.digits
URLSAFE = ALNUM + "_-"
HEX = "0123456789abcdef"
UPPER = string.ascii_uppercase + string.digits


def make_tokens(seed: int = 7) -> dict[str, tuple[str, str]]:
    """label -> (expected finding label, a line as it would appear in a diff)."""
    rnd = random.Random(seed)

    def r(n, alphabet=ALNUM):
        return "".join(rnd.choice(alphabet) for _ in range(n))

    def uid():
        return str(uuid.UUID(int=rnd.getrandbits(128), version=4))

    return {
        "OpenAI classic": ("OpenAI-style sk- key", "key = " + "sk" + "-" + r(48)),
        "OpenAI project": ("OpenAI-style sk- key", "key = " + "sk" + "-proj-" + r(60, URLSAFE)),
        "Anthropic": ("Anthropic key", "key = " + "sk" + "-ant-api03-" + r(80, URLSAFE)),
        "Gemini": ("Gemini key", "key = " + "AI" + "za" + r(35, URLSAFE)),
        "Groq": ("Groq key", "key = " + "gsk" + "_" + r(52)),
        "OpenRouter": ("OpenRouter key", "key = " + "sk" + "-or-v1-" + r(64, HEX)),
        "Cerebras": ("Cerebras key", "key = " + "csk" + "-" + r(48)),
        "SambaNova (variable)": ("SAMBANOVA_API_KEY assigned a value", "SAMBANOVA_API_KEY=" + uid()),
        "Cloudflare token (variable)": ("CLOUDFLARE_API_TOKEN assigned a value", "CLOUDFLARE_API_TOKEN=" + r(40, URLSAFE)),
        "NVIDIA": ("NVIDIA key", "key = " + "nvapi" + "-" + r(64, URLSAFE)),
        "xAI": ("xAI key", "key = " + "xai" + "-" + r(80)),
        "Langfuse secret": ("Langfuse secret key", "key = " + "sk" + "-lf-" + uid()),
        "GitHub token": ("GitHub token", "token " + "gh" + "p_" + r(36)),
        "AWS access key id": ("AWS access key id", "id " + "AK" + "IA" + r(16, UPPER)),
        "Private key": ("private key", "-----BEGIN " + "RSA PRIVATE" + " KEY-----"),
        "Generic assignment": ("secret-like literal assigned to a key, token or password", 'api_key = "' + r(20) + "9" + r(19) + '"'),
    }


TOKENS = make_tokens()


def harmless() -> dict[str, str]:
    rnd = random.Random(11)
    r = lambda n, a=ALNUM: "".join(rnd.choice(a) for _ in range(n))
    return {
        "word containing sk-": "a task-based-evaluation-run-with-many-parts",
        "risk words": "risk-assessment-framework-for-evaluation-runs",
        "sha256 in JSON": '"sha256": "' + r(64, HEX) + '"',
        "uuid as an id": '"id": "' + str(uuid.UUID(int=rnd.getrandbits(128), version=4)) + '"',
        "Cloudflare ACCOUNT id is not a secret": "CLOUDFLARE_ACCOUNT_ID=" + r(32, HEX),
        "empty value": "GROQ_API_KEY=",
        "your-key-here": "SAMBANOVA_API_KEY=your-key-here",
        "long your_ placeholder": "CLOUDFLARE_API_TOKEN=your_cloudflare_api_token_goes_here",
        "angle brackets": "OPENROUTER_API_KEY=<your OpenRouter key>",
        "env reference": "GROQ_API_KEY=${GROQ_API_KEY}",
        "hyphenated word value": 'api_key="routed-by-provider-fallback"',
        "short test value": '"GEMINI_API_KEY": "gm-secret-key-0001"',
        "url": "base = https://api.cerebras.ai/v1/chat/completions",
        "low-entropy long literal": 'token = "' + "a1" * 20 + '"',
    }


@pytest.mark.parametrize("name", TOKENS)
def test_each_provider_format_is_detected_with_its_own_label(name):
    expected, line = TOKENS[name]
    assert expected in guard.find_secrets(line)


def test_a_specific_label_replaces_the_generic_sk_label():
    assert guard.find_secrets(TOKENS["Anthropic"][1]) == ["Anthropic key"]
    assert guard.find_secrets(TOKENS["OpenRouter"][1]) == ["OpenRouter key"]
    assert guard.find_secrets(TOKENS["Langfuse secret"][1]) == ["Langfuse secret key"]


@pytest.mark.parametrize("name", harmless())
def test_harmless_text_and_placeholders_are_not_flagged(name):
    assert guard.find_secrets(harmless()[name]) == []


def test_every_format_is_found_inside_a_diff_and_the_value_is_never_reported():
    for name, (label, line) in TOKENS.items():
        diff = f"+++ b/src/{name.split()[0].lower()}.py\n+{line}"
        findings = guard.scan_diff(diff, {})
        assert any(label in f for f in findings), name
        secret_part = line.split("=", 1)[-1].strip(' "') if "=" in line else line.split()[-1]
        assert all(secret_part not in f for f in findings), f"{name}: the finding repeats the value"


def test_removed_and_context_lines_are_not_scanned():
    diff = "+++ b/a.py\n-" + TOKENS["Groq"][1] + "\n " + TOKENS["Groq"][1]
    assert guard.scan_diff(diff, {}) == []


SHAPELESS = "plain-token-with-no-known-" + "shape-12345"  # a value no format rule recognises; assembled so this file is not itself flagged


def test_env_values_are_found_whatever_their_shape(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("SAMBANOVA_API_KEY=" + SHAPELESS + "\nLANGFUSE_HOST=http://localhost:3000\n", encoding="utf-8")
    monkeypatch.setattr(guard, "ENV_FILE", env)
    assert guard.find_secrets("see " + SHAPELESS) == []  # no format rule knows this value...
    findings = guard.scan_diff("+++ b/x.md\n+see " + SHAPELESS, guard.env_secrets())  # ...but the value check does
    assert findings == ["value of SAMBANOVA_API_KEY from .env appears in x.md"]


def test_entropy_separates_a_secret_from_a_repeated_pattern():
    rnd = random.Random(3)
    assert guard.entropy("a1" * 20) < 3.5 <= guard.entropy("".join(rnd.choice(ALNUM) for _ in range(40)))


def test_an_empty_assignment_never_borrows_the_next_line_as_its_value():
    text = "GROQ_API_KEY=\nSAMBANOVA_API_KEY=\nCLOUDFLARE_API_TOKEN=\nCLOUDFLARE_ACCOUNT_ID=\n"
    assert guard.find_secrets(text) == []


def test_the_repository_itself_has_no_findings():
    """No false positive on real files, and no key-shaped text committed anywhere."""
    files = subprocess.run(["git", "ls-files", "-co", "--exclude-standard"], cwd=ROOT, capture_output=True, text=True, encoding="utf-8").stdout.split()
    flagged = []
    for f in files:
        path = ROOT / f
        if path.is_file():
            if guard.find_secrets(path.read_text(encoding="utf-8", errors="replace")):
                flagged.append(f)
    assert flagged == []


def test_run_results_contain_none_of_the_secret_values_in_env():
    secrets = guard.env_secrets()
    if not secrets or not (ROOT / "eval" / "results").exists():
        pytest.skip("no local .env or no run results on this machine")
    leaked = sorted({name for run in (ROOT / "eval" / "results").glob("*/*") if run.is_file()
                     for name, value in secrets.items() if value in run.read_text(encoding="utf-8", errors="replace")})  # fmt: skip
    assert leaked == [], f"secret values of {leaked} appear in run results"
