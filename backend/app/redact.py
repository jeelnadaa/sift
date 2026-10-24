"""Redact personal identifiers before text leaves for an external LLM (brief section 9).

Kept on purpose: company names, amounts, dates, links (the extraction needs them).
"""
import re

_RULES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\b[2-9]\d{3}\s?\d{4}\s?\d{4}\b"), "[id]"),  # Aadhaar-like 12 digits
    (re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b"), "[id]"),  # PAN
    (re.compile(r"(?<![\w/])(?:\+?91[\s-]?)?[6-9]\d{4}[\s-]?\d{5}\b"), "[phone]"),  # Indian mobile
    (re.compile(r"(?<![\w/])\+\d{1,3}[\s-]?\d{2,4}[\s-]?\d{3,4}[\s-]?\d{3,4}\b"), "[phone]"),  # international
    (re.compile(r"\b\d{2}[A-Z]{2,4}\d{3,5}\b"), "[roll]"),  # roll numbers like 21BCE1234
    (re.compile(r"(?<![\w/=?&.-])\d{9,18}\b"), "[number]"),  # account / card / long ids (not inside URLs)
    (re.compile(r"\b(?:x{2,}|X{2,}|\*{2,})\d{3,6}\b"), "[number]"),  # masked card/account like XX1234
    (re.compile(r"\b([A-Za-z0-9._%+-]+)@([A-Za-z0-9.-]+\.[A-Za-z]{2,})\b"), r"[email]@\2"),  # keep the domain
]


def redact(text: str) -> str:
    for pattern, repl in _RULES:
        text = pattern.sub(repl, text)
    return text
