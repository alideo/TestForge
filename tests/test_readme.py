"""QA tests validating README.md against the PR acceptance criteria.

Each test maps to an acceptance criterion (AC1..AC6). The tests operate on the
raw bytes/text of the README at the repository root so that structural rules
(headings, numbered steps, code blocks, trailing newline, secret hygiene) are
verified exactly as they appear on disk.
"""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
README = REPO_ROOT / "README.md"


# --------------------------------------------------------------------------- #
# Fixtures / helpers
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def raw_bytes() -> bytes:
    return README.read_bytes()


@pytest.fixture(scope="module")
def text(raw_bytes: bytes) -> str:
    return raw_bytes.decode("utf-8")


@pytest.fixture(scope="module")
def lines(text: str):
    return text.splitlines()


def _non_code_lines(text: str):
    """Yield lines that are NOT inside fenced ``` code blocks.

    Heading/secret checks should ignore fenced code so that example commands
    do not create false positives or false negatives.
    """
    out = []
    in_fence = False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if not in_fence:
            out.append(line)
    return out


# --------------------------------------------------------------------------- #
# AC1 — README.md exists at repository root
# --------------------------------------------------------------------------- #
def test_ac1_readme_exists_at_root():
    assert README.is_file(), "README.md must exist at the repository root"


def test_ac1_readme_not_empty(raw_bytes):
    assert len(raw_bytes) > 0, "README.md must not be empty"


# --------------------------------------------------------------------------- #
# AC2 — H1 title and at least four H2 sections
# --------------------------------------------------------------------------- #
def test_ac2_has_single_h1(text):
    h1s = [ln for ln in _non_code_lines(text) if re.match(r"^# \S", ln)]
    assert len(h1s) >= 1, "README must contain an H1 title (# ...)"
    assert len(h1s) == 1, f"README should have exactly one H1, found {len(h1s)}: {h1s}"


def test_ac2_first_heading_is_h1(text):
    headings = [ln for ln in _non_code_lines(text) if re.match(r"^#{1,6} ", ln)]
    assert headings, "README must contain headings"
    assert headings[0].startswith("# "), "The first heading should be the H1 title"


def test_ac2_has_at_least_four_h2(text):
    h2s = [ln for ln in _non_code_lines(text) if re.match(r"^## \S", ln)]
    assert len(h2s) >= 4, f"README needs >= 4 H2 sections, found {len(h2s)}: {h2s}"


# --------------------------------------------------------------------------- #
# AC3 — Installation section has numbered, sequential steps
# --------------------------------------------------------------------------- #
def _section_body(text: str, heading_regex: str):
    """Return the lines belonging to the first H2 whose title matches regex."""
    lines = text.splitlines()
    body, capturing = [], False
    for ln in lines:
        if re.match(r"^## ", ln):
            if capturing:  # reached the next section
                break
            if re.search(heading_regex, ln, re.IGNORECASE):
                capturing = True
                continue
        if capturing:
            body.append(ln)
    return body


def test_ac3_installation_section_exists(text):
    body = _section_body(text, r"install")
    assert body, "An '## Installation' section must exist"


def test_ac3_installation_steps_are_numbered_and_sequential(text):
    body = _section_body(text, r"install")
    # Only top-level ordered list markers (no leading indentation).
    numbers = [
        int(m.group(1))
        for ln in body
        if (m := re.match(r"^(\d+)\.\s+\S", ln))
    ]
    assert numbers, "Installation section must contain numbered steps (1. 2. ...)"
    assert len(numbers) >= 2, f"Installation should have multiple steps, found {numbers}"
    assert numbers == list(
        range(numbers[0], numbers[0] + len(numbers))
    ), f"Installation steps must be sequential, found {numbers}"
    assert numbers[0] == 1, f"Installation steps should start at 1, found {numbers[0]}"


# --------------------------------------------------------------------------- #
# AC4 — Usage/getting-started example present with a code block
# --------------------------------------------------------------------------- #
def test_ac4_usage_section_exists(text):
    body = _section_body(text, r"usage|getting[- ]started|quick[- ]?start")
    assert body, "A usage / getting-started section must exist"


def test_ac4_usage_section_has_code_block(text):
    body = _section_body(text, r"usage|getting[- ]started|quick[- ]?start")
    fences = [ln for ln in body if ln.lstrip().startswith("```")]
    assert len(fences) >= 2, (
        "Usage/getting-started section must contain a fenced code block "
        f"(found {len(fences)} fence markers)"
    )


def test_ac4_code_fences_are_balanced(text):
    fences = [ln for ln in text.splitlines() if ln.lstrip().startswith("```")]
    assert len(fences) % 2 == 0, "All fenced code blocks must be closed (balanced ```)"


# --------------------------------------------------------------------------- #
# AC5 — No hardcoded secrets, credentials, or environment-specific values
# --------------------------------------------------------------------------- #
# Patterns that indicate a *real* leaked secret/value (placeholders are allowed).
SECRET_PATTERNS = [
    # key = value assignments with a long real-looking token
    (r"(?i)(api[_-]?key|secret|token|password|passwd|access[_-]?key)\s*[:=]\s*['\"]?[A-Za-z0-9/+]{16,}", "hardcoded credential value"),
    # AWS access key id
    (r"AKIA[0-9A-Z]{16}", "AWS access key id"),
    # Private key blocks
    (r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----", "private key block"),
    # Bearer tokens with real-looking payloads
    (r"(?i)bearer\s+[A-Za-z0-9\-_\.]{20,}", "bearer token"),
    # Hardcoded IP:port endpoints (env-specific)
    (r"\b(?:\d{1,3}\.){3}\d{1,3}:\d{2,5}\b", "hardcoded host:port"),
]

# Obvious placeholder tokens that should NOT be flagged.
PLACEHOLDER_ALLOWLIST = re.compile(
    r"(?i)your-org|your-repo|your_package|<[A-Za-z0-9_]+>|example\.com|xxxx|placeholder"
)


def test_ac5_no_hardcoded_secrets(text):
    findings = []
    for ln in text.splitlines():
        if PLACEHOLDER_ALLOWLIST.search(ln):
            continue
        for pattern, label in SECRET_PATTERNS:
            if re.search(pattern, ln):
                findings.append(f"{label}: {ln.strip()}")
    assert not findings, "Possible hardcoded secrets/env-specific values:\n" + "\n".join(findings)


def test_ac5_env_placeholders_use_obvious_tokens(text):
    # If API_KEY / API_HOST are mentioned, they must reference a placeholder,
    # not a concrete value.
    for ln in text.splitlines():
        m = re.search(r"(?i)\b(API[_-]?KEY|API[_-]?HOST)\b\s*[:=]?\s*(.+)$", ln)
        if m and "e.g." not in ln.lower() and not ln.lstrip().startswith(("-", "*", "#", ">")):
            value = m.group(2).strip().strip("`'\"")
            if value and not PLACEHOLDER_ALLOWLIST.search(value):
                pytest.fail(f"Env value should be a placeholder, got: {ln.strip()}")


# --------------------------------------------------------------------------- #
# AC6 — File ends with a trailing newline
# --------------------------------------------------------------------------- #
def test_ac6_ends_with_trailing_newline(raw_bytes):
    assert raw_bytes.endswith(b"\n"), "README.md must end with a trailing newline"


def test_ac6_single_trailing_newline(raw_bytes):
    assert not raw_bytes.endswith(b"\n\n"), (
        "README.md should end with exactly one trailing newline (no blank line at EOF)"
    )


def test_ac6_no_trailing_whitespace_lines(text):
    offenders = [
        i + 1 for i, ln in enumerate(text.splitlines()) if ln != ln.rstrip()
    ]
    assert not offenders, f"Lines with trailing whitespace: {offenders}"
