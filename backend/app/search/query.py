"""Search query parsing (brief section 19).

A query mixes Gmail's own syntax with filters only Sift can answer. Parsing splits it:
- the **Gmail part** is passed to Gmail unchanged, so typing Gmail syntax behaves exactly as
  in Gmail: every operator (from:, to:, subject:, label:, in:, is:unread, has:attachment,
  filename:, larger:, after:, older_than:, list:, deliveredto:, rfc822msgid:, …), "exact
  phrases", OR, -negation, (groups), {either-or} and AROUND;
- the **Sift part** is a list of filters on our own data:

    folder:NAME | folder:none     in that folder or its subfolders / in no folder
    tag:NAME                       tagged
    priority:urgent|normal|digest|silent
    type:NAME                      Sift category (e.g. type:assessment_link)
    company:NAME                   on that company's timeline
    account:EMAIL-OR-LABEL         only that connected account (also limits which accounts Gmail searches)
    rule:NAME                      decided by that rule
    is:silenced  is:grouped  is:notified  is:acked  is:snoozed  has:note  has:link
    saved:NAME                     everything a saved search matches

Any Sift filter can be negated with "-" and several can be OR-ed inside braces:
{folder:Work folder:Placements}. Names with spaces go in quotes: folder:"Job hunt".
"""
import re
from dataclasses import dataclass, field

SIFT_KEYS = {"folder", "group", "tag", "priority", "type", "company", "account", "rule", "saved"}
SIFT_IS = {"silenced", "grouped", "notified", "acked", "snoozed", "pinned"}
SIFT_HAS = {"note", "link"}
PRIORITIES = {"urgent", "normal", "digest", "silent"}
MAX_QUERY = 1000
MAX_TOKENS = 60


class QueryError(ValueError):
    pass


@dataclass(frozen=True)
class Filter:
    key: str  # folder, tag, priority, type, company, account, rule, saved, is, has
    value: str
    negated: bool = False

    def text(self) -> str:
        v = f'"{self.value}"' if re.search(r"[\s(){}\"]", self.value) else self.value
        return f"{'-' if self.negated else ''}{self.key}:{v}"


@dataclass
class Chip:
    text: str  # exactly as it goes back into the query string
    kind: str  # "gmail" or "sift"
    label: str  # human wording for the chip
    negated: bool = False


@dataclass
class Parsed:
    gmail: str = ""  # the Gmail part, ready for users.messages.list q=
    filters: list[Filter] = field(default_factory=list)  # all must match
    any_of: list[list[Filter]] = field(default_factory=list)  # each group: at least one must match
    words: list[str] = field(default_factory=list)  # plain words and phrases in the Gmail part (local fallback, highlighting)
    chips: list[Chip] = field(default_factory=list)

    @property
    def has_gmail(self) -> bool:
        return bool(self.gmail.strip())


_TOKEN = re.compile(r"""
    \s*(
      -?"[^"]*"?                                   # "exact phrase" (unclosed tolerated)
    | -?[\w.+-]+:"[^"]*"?                          # op:"quoted value"
    | -?[\w.+-]+:\([^)]*\)?                        # op:(grouped values)
    | -?\{[^}]*\}?                                 # {either or}
    | -?\([^)]*\)?                                 # (group)
    | [^\s"(){}]+                                  # word, op:value, OR, AROUND, -word
    )""", re.X)


def tokenize(q: str) -> list[str]:
    if len(q) > MAX_QUERY:
        raise QueryError(f"search is too long ({MAX_QUERY} characters at most)")
    out, pos = [], 0
    while pos < len(q):
        m = _TOKEN.match(q, pos)
        if not m or not m.group(1):
            break
        out.append(m.group(1))
        pos = m.end()
    if len(out) > MAX_TOKENS:
        raise QueryError("search has too many parts")
    return out


def _unquote(v: str) -> str:
    v = v.strip()
    if v.startswith('"'):
        v = v[1:-1] if v.endswith('"') and len(v) > 1 else v[1:]
    return v.strip()


def _sift_filter(token: str) -> Filter | None:
    neg = token.startswith("-")
    body = token[1:] if neg else token
    if ":" not in body:
        return None
    key, _, value = body.partition(":")
    key, value = key.lower(), _unquote(value)
    if key in SIFT_KEYS and value:
        if key == "priority":
            if value.lower() not in PRIORITIES:
                raise QueryError("priority: takes urgent, normal, digest or silent")
            value = value.lower()
        return Filter(key, value, neg)
    if key == "is" and value.lower() in SIFT_IS:
        return Filter("is", value.lower(), neg)
    if key == "has" and value.lower() in SIFT_HAS:
        return Filter("has", value.lower(), neg)
    return None


LABELS = {
    "folder": "In folder", "group": "In group", "tag": "Tag", "priority": "Priority", "type": "Category", "company": "Company",
    "account": "Account", "rule": "Rule", "saved": "Saved search",
    "is:silenced": "Silenced", "is:grouped": "In a group", "is:snoozed": "Snoozed", "is:notified": "Notified", "is:acked": "Notification delivered", "is:pinned": "Pinned",
    "has:note": "Has a note", "has:link": "Has a link",
}


def _chip_label(f: Filter) -> str:
    base = LABELS.get(f"{f.key}:{f.value}") or f"{LABELS.get(f.key, f.key)}: {f.value}"
    if f.key == "folder" and f.value.lower() == "none":
        base = "In no folder"
    return ("Not " + base[0].lower() + base[1:]) if f.negated else base


def parse(q: str) -> Parsed:
    out = Parsed()
    gmail_tokens: list[str] = []
    for tok in tokenize(q or ""):
        if tok.lstrip("-").startswith("{"):
            inner = tok.lstrip("-").strip("{}")
            parts = tokenize(inner)
            filters = [_sift_filter(p) for p in parts]
            if parts and all(filters):
                if tok.startswith("-"):
                    raise QueryError("negate Sift filters one by one, e.g. -folder:A -folder:B")
                out.any_of.append(filters)  # type: ignore[arg-type]
                out.chips.append(Chip(tok, "sift", "Any of: " + ", ".join(_chip_label(f) for f in filters)))
                continue
            if any(filters):
                raise QueryError("don't mix Sift filters and Gmail words inside one {…}")
        f = _sift_filter(tok)
        if f:
            out.filters.append(f)
            out.chips.append(Chip(f.text(), "sift", _chip_label(f), f.negated))
            continue
        gmail_tokens.append(tok)
        out.chips.append(Chip(tok, "gmail", tok, tok.startswith("-")))
        after_around = len(gmail_tokens) > 1 and gmail_tokens[-2].upper() == "AROUND" and tok.isdigit()
        if not after_around and not re.match(r"-?[\w.+-]+:", tok) and tok.upper() not in ("OR", "AND", "AROUND") and not tok.lstrip("-").startswith(("(", "{")):
            word = _unquote(tok.lstrip("-"))
            if word and not tok.startswith("-"):
                out.words.append(word)
    # "OR" next to a Sift filter would silently change meaning in Gmail: refuse instead
    if gmail_tokens and gmail_tokens[0].upper() == "OR" or gmail_tokens and gmail_tokens[-1].upper() == "OR":
        raise QueryError("OR needs something on both sides (use {…} to OR Sift filters)")
    out.gmail = " ".join(gmail_tokens)
    return out


def build(chips: list[str]) -> str:
    """Chips back into a query string (the builder and the string convert both ways)."""
    return " ".join(c.strip() for c in chips if c and c.strip())
