"""Mask obvious identifiers before text leaves for an external LLM.

This is minimisation, not de-identification: it covers emails, phone-like and Medicare-style
numbers and dates of birth, and does NOT catch names, addresses or free-text details. A real
deployment needs a vetted de-identification step and a data-processing agreement with the provider.
"""

from __future__ import annotations

import re

_PATTERNS = [
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "[EMAIL]"),
    (re.compile(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b"), "[DATE]"),
    (re.compile(r"(?<![\d$,.])(?:\+?61|0)[\d\s-]{8,12}\d(?![\d,]*\s*(?:days|dollars|%))"), "[PHONE]"),
    (re.compile(r"(?<![\d$,.])\d{4}[\s-]?\d{5}[\s-]?\d(?![\d,])"), "[ID_NUMBER]"),
]


def redact(text: str) -> str:
    for pat, label in _PATTERNS:
        text = pat.sub(label, text)
    return text
