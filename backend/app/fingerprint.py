"""Subject fingerprints (brief section 7 step 7).

A fingerprint is the subject with the variable parts replaced (numbers, amounts, dates,
ids, addresses), hashed together with the sender's authenticated domain. "UPI debit of
Rs 240 on 12-10-2026" and "UPI debit of Rs 1,180 on 13-10-2026" share one fingerprint, so
once a rule or the user silences one, the next is handled the same way for free.
"""
import hashlib
import re

_STEPS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"^((re|fwd?|fw)\s*:\s*)+", re.I), ""),
    (re.compile(r"https?://\S+"), "<url>"),
    (re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"), "<email>"),
    (re.compile(r"(?:₹|rs\.?|inr|usd|\$|€|£)\s*[\d,]+(?:\.\d+)?", re.I), "<amount>"),
    (re.compile(r"[\d,]+(?:\.\d+)?\s*(?:rs|inr|rupees)\b", re.I), "<amount>"),
    (re.compile(r"\b\d{1,4}[-/.]\d{1,2}[-/.]\d{1,4}\b"), "<date>"),
    (re.compile(r"\b\d{1,2}\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?(\s+\d{2,4})?\b", re.I), "<date>"),
    (re.compile(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+\d{1,2}(,?\s+\d{4})?\b", re.I), "<date>"),
    (re.compile(r"\b\d{1,2}:\d{2}(:\d{2})?\s*(am|pm)?\b", re.I), "<time>"),
    (re.compile(r"\b(?=[a-z]*\d)(?=\d*[a-z])[a-z0-9]{6,}\b", re.I), "<id>"),  # mixed letters+digits
    (re.compile(r"[x*]{2,}\d+", re.I), "<num>"),  # masked numbers like XX1234
    (re.compile(r"#?\d+"), "<num>"),
    (re.compile(r"\s+"), " "),
]


def normalize_subject(subject: str) -> str:
    s = subject.strip()
    for pattern, repl in _STEPS:
        s = pattern.sub(repl, s)
    return s.strip().lower()


def fingerprint(domain: str, subject: str) -> str:
    return hashlib.sha256(f"{domain.lower()}|{normalize_subject(subject)}".encode()).hexdigest()[:32]
