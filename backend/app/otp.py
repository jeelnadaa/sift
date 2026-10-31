"""One-time codes (OTP) in mail: found locally, no AI, so it works with AI off (owner, 2026-10-31).

The code is never stored or logged. It is found while a new mail is processed (rides only in that
mail's notification, for the "Copy code" button) and again live when the mail is opened.

Rules, in order of trust:
- a code needs an OTP phrase near it: "OTP", "one-time password", "verification code",
  "security code", "sign-in code", "passcode", ..., or a bare "code"/"PIN" directly followed by
  "is" / ":" ("Your code is 482913"). Promo, coupon, referral, postal and pin codes do not count;
- 4-8 digits (also "123 456" / "1234-5678"), or 4-8 capitals and digits right after "is"/":";
- never an amount (₹/Rs/INR/$ before it), a year, a time, a date, a phone number, a masked card or
  account ("XX1234", "ending 1234") or an order/reference/transaction number.
When unsure it finds nothing: a missed code costs a tap, a wrong one is worse.
"""
import re

SCAN_CHARS = 6000  # codes sit near the top; long newsletters are not scanned to the end
AFTER = 110  # how far after the phrase a code may be ("OTP for txn of INR 2,500.00 at X on card XX12 is 482913")
BEFORE = 40  # "482913 is your verification code"

_NOT_OTP_CODE = r"(?<!promo )(?<!coupon )(?<!discount )(?<!referral )(?<!invite )(?<!postal )(?<!zip )(?<!area )(?<!country )(?<!error )(?<!status )(?<!ifsc )(?<!swift )(?<!hsn )(?<!sac )(?<!source )(?<!qr )(?<!bar )(?<!pin )(?<!gift )(?<!voucher )(?<!offer )(?<!sale )(?<!deal )"
PHRASE = re.compile(
    r"\b(?:otps?|one[\s-]?time[\s-]?(?:password|passcode|pass\s?code|code|pin)"
    r"|(?:verification|security|confirmation|authentication|auth|access|login|log[\s-]?in|sign[\s-]?in|2fa|mfa|two[\s-]?(?:factor|step)(?:\s+verification)?|single[\s-]use|secure)\s+(?:code|pin)"
    r"|passcode|verification\s+number"
    rf"|{_NOT_OTP_CODE}(?:code|pin)(?=\s*(?:is\b|:|=|-\s)))",
    re.I,
)
MENTION = re.compile(r"\b(?:otp|one[\s-]?time|passcode|verification|verify|security code|sign[\s-]?in code|log[\s-]?in code|2fa|code is|code:|pin is|pin:)", re.I)

_DIGITS = r"(?<![\w/:.,#+*@-])(?<!\d )(?<!\d-)(\d{3}[ -]\d{3}|\d{4}[ -]\d{4}|\d{4,8})(?![ -]?\d)(?![\w/:%@]|[.,]\d)"
DIGITS = re.compile(_DIGITS)
ALNUM = re.compile(r"(?:\bis|:|=)\s*\(?\b((?=[A-Z0-9]*\d)(?=[A-Z0-9]*[A-Z])[A-Z0-9]{4,8})\b(?![-/@.]\w)")

# what may not come right before a number for it to be a code
_BAD_BEFORE = re.compile(
    r"(?:₹|\$|€|£|\brs\.?|\binr|\busd|\beur|\bamount|\bamt|\bbal(?:ance)?|\ba/c|\bacc(?:oun)?t|\bacct|\bcard|\bending(?:\s+(?:in|with))?|\bx{2,}|\*{2,}"
    r"|\border|\bref(?:erence)?|\btxn|\btransaction|\btrans|\bid|\bno|\bnumber|#|\btracking|\bawb|\binvoice|\bbill|\bpolicy|\bphone|\bmobile|\bcall|\btel|\bfax|\bext"
    r"|\broll|\breg(?:istration)?|\bemp(?:loyee)?|\bticket|\bcase|\bpnr|\bupi|\butr|\brrn|\bpin\s?code|\bpincode|\bzip|\bat|\bon|\bvalid|\bfor|\bin|\bwithin|\bexpires?)"
    r"\s*(?:no\.?|number|#|id)?\s*[:.#-]?\s*$",
    re.I,
)
_BAD_AFTER = re.compile(r"^\s*(?:%|rs\b|inr\b|/-|mins?\b|minutes?\b|hours?\b|hrs?\b|secs?\b|seconds?\b|days?\b|am\b|pm\b|ist\b|utc\b)", re.I)


def _clean(text: str) -> str:
    return re.sub(r"[ \t ​]+", " ", text or "")[:SCAN_CHARS]


def mentioned(*texts: str | None) -> bool:
    """Cheap first check (subject, preview): might this mail carry a code?"""
    return any(MENTION.search(t or "") for t in texts)


def _ok(text: str, start: int, end: int, code: str) -> bool:
    before, after = text[max(0, start - 24):start], text[end:end + 12]
    if _BAD_BEFORE.search(before) or _BAD_AFTER.match(after):
        return False
    digits = re.sub(r"[ -]", "", code)
    if len(digits) == 4 and digits.isdigit() and 1900 <= int(digits) <= 2099:
        return False  # a year
    return not (digits.isdigit() and len(set(digits)) == 1)  # 0000, 111111: placeholders, not codes


def _near(text: str, lo: int, hi: int, at: int) -> str | None:
    """The candidate code in text[lo:hi] closest to position `at`."""
    found: list[tuple[int, str]] = []
    for rx in (DIGITS, ALNUM):
        for m in rx.finditer(text, lo, hi):
            if _ok(text, m.start(1), m.end(1), m.group(1)):
                found.append((min(abs(m.start(1) - at), abs(m.end(1) - at)), m.group(1)))
    if not found:
        return None
    return re.sub(r"[ -]", "", min(found)[1])


def find(subject: str | None, body: str | None) -> str | None:
    """The one-time code in this mail, or None. Looks after each OTP phrase first, then before it."""
    text = _clean(f"{subject or ''}\n{body or ''}")
    for m in PHRASE.finditer(text):
        code = _near(text, m.end(), min(len(text), m.end() + AFTER), m.end())
        if code:
            return code
    for m in PHRASE.finditer(text):
        code = _near(text, max(0, m.start() - BEFORE), m.start(), m.start())
        if code:
            return code
    return None
