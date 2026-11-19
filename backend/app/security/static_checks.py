"""Deterministic checks on proposed code. They run regardless of what the LLM reviewer says."""
import re

RULES = [
    ("high", "Possible hardcoded secret", re.compile(
        r"(?i)(api[_-]?key|secret|token|passwd|password)\s*[:=]\s*[\"'][^\"']{8,}[\"']")),
    ("high", "Looks like an API key", re.compile(r"\b(sk-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16})\b")),
    ("high", "eval/exec on dynamic input", re.compile(r"(?<![\w.])(eval|exec)\s*\(")),
    ("high", "Shell command execution", re.compile(r"os\.system\s*\(|shell\s*=\s*True")),
    ("high", "TLS certificate verification disabled", re.compile(r"verify\s*=\s*False")),
    ("medium", "Unsafe deserialization", re.compile(r"pickle\.loads?\s*\(|yaml\.load\s*\(")),
    ("medium", "Possible SQL built from strings", re.compile(r"execute\s*\(\s*(f[\"']|[\"'].*[\"']\s*(%|\+|\.format))")),
    ("medium", "Raw HTML injection", re.compile(r"innerHTML\s*=|dangerouslySetInnerHTML")),
]


def scan_changes(changes: list[dict]) -> list[dict]:
    """Scan only lines the change adds (new code that was not already in the old code)."""
    flags = []
    for c in changes:
        old_lines = {line.strip() for line in c.get("old", "").splitlines()}
        start = c.get("line")
        for i, line in enumerate(c.get("new", "").splitlines()):
            if line.strip() in old_lines:
                continue
            for severity, rule, pattern in RULES:
                if pattern.search(line):
                    flags.append({"path": c["path"], "severity": severity, "rule": rule,
                                  "line": start + i if start else None, "text": line.strip()[:120]})
    return flags