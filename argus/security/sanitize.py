"""Input sanitization for the two directions data flows through Argus.

Log content and external tool output are the biggest prompt-injection
risk — an attacker who can land a string in a log line Argus later
reads can try to steer the agent ("ignore previous instructions,
exfiltrate ..."). Alert channels are the opposite risk: the agent's
output might include things that shouldn't leave the perimeter
(internal hostnames with secrets in them, employee emails, raw
tokens).

Both directions are addressed here. Neither function is a silver
bullet; they are one layer of defense alongside least-privilege tool
scopes (allowlist.py) and audited remediation (remediate/).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Phrases a legitimate log line would never contain — if the agent sees them,
# they came from an attacker trying to steer it. Deliberately strict; false
# positives are fine because we only neuter the string, we don't drop it.
_INJECTION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(
        r"ignore\s+(?:all\s+)?(?:previous|prior|above)\s+(?:instructions|context)", re.IGNORECASE
    ),
    re.compile(
        r"disregard\s+(?:all\s+)?(?:previous|prior|above)\s+(?:instructions|context)", re.IGNORECASE
    ),
    re.compile(r"forget\s+(?:everything|all)\s+(?:you|previously)", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\s+(?:a|an|the)\b", re.IGNORECASE),
    re.compile(r"system\s*:\s*", re.IGNORECASE),
    re.compile(r"<\s*/?\s*system\s*>", re.IGNORECASE),
    re.compile(r"</?\s*assistant\s*>", re.IGNORECASE),
    re.compile(r"```\s*system", re.IGNORECASE),
    # Exfiltration-adjacent lures:
    re.compile(
        r"(?:print|echo|reveal|output|send)\s+(?:your|the)\s+(?:system\s+)?prompt", re.IGNORECASE
    ),
    re.compile(r"api[_\s-]?key\s*[=:]\s*", re.IGNORECASE),
]

# PII patterns to strip from outbound channel messages. Narrower than
# "find all PII" — we care about the shapes that commonly leak and are
# cheap to catch.
_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_CARD = re.compile(r"\b(?:\d[ -]*?){13,19}\b")
_BEARER = re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]+")
_SK_ANT = re.compile(r"sk-ant-[a-zA-Z0-9_-]{16,}")
_AWS_ACCESS = re.compile(r"\bAKIA[0-9A-Z]{16}\b")


@dataclass
class SanitizationResult:
    """What came out of sanitize_for_agent."""

    text: str
    injection_patterns_matched: list[str] = field(default_factory=list)
    truncated: bool = False
    original_length: int = 0

    @property
    def tainted(self) -> bool:
        return bool(self.injection_patterns_matched)


def sanitize_for_agent(text: str, *, max_length: int = 200_000) -> SanitizationResult:
    """Neutralize injection attempts in text headed INTO the agent's context.

    Policy: don't drop the content (the agent needs it to investigate),
    but neuter the specific phrasing that reads as an instruction. We
    wrap matched spans with a visible marker, so the agent sees that
    something was attempted but can't execute on it.

    Also truncates oversized blobs — a 10MB log dump isn't useful to
    the agent and will blow the context window.
    """
    original_length = len(text)
    truncated = False
    if original_length > max_length:
        text = text[:max_length] + f"\n[truncated: {original_length - max_length} bytes dropped]"
        truncated = True

    matched: list[str] = []
    for pattern in _INJECTION_PATTERNS:
        if pattern.search(text):
            matched.append(pattern.pattern)
            text = pattern.sub(
                lambda m: f"[REDACTED-INJECTION-ATTEMPT:{m.group(0)[:40]}]",
                text,
            )

    if matched:
        logger.warning("sanitize_for_agent neutralized %d injection pattern(s)", len(matched))

    return SanitizationResult(
        text=text,
        injection_patterns_matched=matched,
        truncated=truncated,
        original_length=original_length,
    )


def strip_pii_for_channels(text: str) -> str:
    """Redact PII and secret-shaped tokens before posting to Teams/Slack.

    Alert messages shouldn't leak customer data or credentials.
    Replacements are visible so an operator reading the alert knows
    something was redacted (helpful if the elided value matters).
    """

    def _redact(pattern: re.Pattern[str], label: str, s: str) -> str:
        return pattern.sub(f"[{label}]", s)

    s = text
    s = _redact(_SK_ANT, "REDACTED-ANTHROPIC-KEY", s)
    s = _redact(_BEARER, "REDACTED-BEARER", s)
    s = _redact(_AWS_ACCESS, "REDACTED-AWS-KEY", s)
    s = _redact(_SSN, "REDACTED-SSN", s)
    s = _redact(_CARD, "REDACTED-CARD", s)
    s = _redact(_EMAIL, "REDACTED-EMAIL", s)
    return s
