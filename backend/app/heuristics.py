"""Free heuristics (brief section 7 step 6). They only ever suggest "digest" and never override
a user rule. Uncertain mail stays normal priority.

- strong: Gmail Promotions/Social tab -> digest, and the LLM is skipped (no tokens spent).
- weak:   bulk-mail headers or a no-reply sender. Recorded as a hint only; it does not change
          priority. Placement cells mail through lists and assessment platforms send from
          no-reply addresses, so demoting these would hide exactly the mail that matters.
"""
import re
from dataclasses import dataclass

from app.mail.message import MailMeta

NO_REPLY = re.compile(r"^(no[-_.]?reply|do[-_.]?not[-_.]?reply|notifications?|alerts?|mailer-daemon|bounce)", re.I)


@dataclass(frozen=True)
class Suggestion:
    action: str  # "digest"
    strength: str  # "strong" | "weak"
    reason: str


def suggest(meta: MailMeta) -> Suggestion | None:
    labels = set(meta.labels)
    if labels & {"CATEGORY_PROMOTIONS", "CATEGORY_SOCIAL"}:
        return Suggestion("digest", "strong", "gmail_category")
    precedence = (meta.header("precedence") or "").lower()
    if meta.header("list-unsubscribe") or meta.list_id or precedence in ("bulk", "list", "junk"):
        return Suggestion("digest", "weak", "bulk_headers")
    if NO_REPLY.match(meta.sender.split("@")[0]):
        return Suggestion("digest", "weak", "no_reply_sender")
    return None
