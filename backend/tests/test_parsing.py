import base64

import pytest

from app.fingerprint import fingerprint, normalize_subject
from app.heuristics import suggest
from app.mail.message import authenticated_domain, clean_body, extract_body, html_to_text, parse_metadata
from app.redact import redact


def b64(s):
    return base64.urlsafe_b64encode(s.encode()).decode()


def gmail_msg(headers: dict, labels=("INBOX",), auth=None):
    hs = [{"name": k, "value": v} for k, v in headers.items()]
    for a in auth or []:
        hs.append({"name": "Authentication-Results", "value": a})
    return {"id": "m1", "threadId": "t1", "labelIds": list(labels), "snippet": "Hi &amp; bye", "internalDate": "1761300000000",
            "payload": {"mimeType": "multipart/mixed", "headers": hs}}


# ---- authentication -----------------------------------------------------------------

GOOGLE_PASS = "mx.google.com; dkim=pass header.i=@kotak.com header.s=s1; spf=pass (google.com: domain of alerts@kotak.com designates 1.2.3.4) smtp.mailfrom=alerts@kotak.com; dmarc=pass (p=REJECT) header.from=kotak.com"


def test_authenticated_when_gmail_reports_pass():
    assert authenticated_domain([GOOGLE_PASS], "kotak.com") == "kotak.com"
    assert authenticated_domain(["mx.google.com; dkim=pass header.i=@mail.kotak.com"], "kotak.com") == "kotak.com"


@pytest.mark.parametrize("results", [
    ["mx.google.com; dkim=fail header.i=@kotak.com; spf=softfail smtp.mailfrom=evil.example; dmarc=fail header.from=kotak.com"],
    ["mx.google.com; dkim=pass header.i=@evil.example; spf=pass smtp.mailfrom=bounce@evil.example"],  # passes, but for another domain
    ["relay.evil.example; dkim=pass header.i=@kotak.com; dmarc=pass header.from=kotak.com"],  # forged by an earlier hop
    [],
])
def test_spoofed_or_unauthenticated_mail(results):
    assert authenticated_domain(results, "kotak.com") is None


def test_parse_metadata():
    m = parse_metadata(gmail_msg({
        "From": '"Kotak Bank" <Alerts@Kotak.com>', "To": "me@gmail.com", "Cc": "x@y.com", "Subject": " Rs 240 debited ",
        "Message-ID": "<abc@kotak.com>", "List-Id": "<alerts.kotak.com>", "Content-Type": "multipart/mixed; boundary=x",
    }, labels=("INBOX", "UNREAD"), auth=["relay.x; dkim=pass header.i=@evil.com", GOOGLE_PASS]))
    assert (m.sender, m.sender_name, m.sender_domain, m.authenticated_domain) == ("alerts@kotak.com", "Kotak Bank", "kotak.com", "kotak.com")
    assert (m.subject, m.message_id, m.list_id, m.has_attachment) == ("Rs 240 debited", "<abc@kotak.com>", "<alerts.kotak.com>", True)
    assert m.snippet == "Hi & bye" and m.recipients == ["me@gmail.com", "x@y.com"]
    assert m.received_at.year == 2025


# ---- body ----------------------------------------------------------------------------

def test_extract_body_prefers_plain_and_lists_attachments():
    payload = {"mimeType": "multipart/mixed", "parts": [
        {"mimeType": "multipart/alternative", "parts": [
            {"mimeType": "text/plain", "body": {"data": b64("Plain text")}},
            {"mimeType": "text/html", "body": {"data": b64("<p>Html</p>")}},
        ]},
        {"mimeType": "application/pdf", "filename": "offer.pdf", "body": {"attachmentId": "a1"}},
    ]}
    assert extract_body(payload) == ("Plain text", ["offer.pdf"])


def test_html_to_text_drops_scripts_and_keeps_links():
    text = html_to_text('<style>p{}</style><p>Start the <a href="https://t.in/x">test</a></p><script>evil()</script>')
    assert "evil" not in text and "p{}" not in text
    assert "https://t.in/x" in text and "Start the" in text


def test_clean_body_strips_quotes_and_signature_and_truncates():
    raw = "Hello\n\n\n\nPlease register.\n> old quoted line\n-- \nPriya\nRecruiter\nOn Mon, 1 Jan 2026 at 10:00, Bob <b@x.com> wrote:\nold"
    assert clean_body(raw) == "Hello\n\nPlease register."
    assert len(clean_body("x" * 5000)) == 1500


# ---- redaction ------------------------------------------------------------------------

def test_redaction_removes_identifiers_but_keeps_links_and_amounts():
    text = ("Roll 21BCE1234, call +91 98765 43210 or 9876543210. A/c XX1234, ref 431234567890. "
            "Aadhaar 2345 6789 0123, PAN ABCDE1234F. Mail priya@globex.com. Pay Rs 1,180 at https://assess.hirepro.in/t/8dk2Q?id=123456789")
    out = redact(text)
    for secret in ("21BCE1234", "98765 43210", "9876543210", "XX1234", "431234567890", "2345 6789 0123", "ABCDE1234F", "priya@"):
        assert secret not in out
    assert "@globex.com" in out and "Rs 1,180" in out
    assert "https://assess.hirepro.in/t/8dk2Q?id=123456789" in out


# ---- fingerprints -------------------------------------------------------------------------

def test_fingerprint_ignores_variable_parts():
    a = "Rs 240.00 debited from A/c XX1234 on 24-10-2026 at 10:15 AM"
    b = "Rs 1,180.50 debited from A/c XX9876 on 25-10-2026 at 9:02 PM"
    assert normalize_subject(a) == normalize_subject(b)
    assert fingerprint("kotak.com", a) == fingerprint("kotak.com", b)
    assert fingerprint("kotak.com", a) != fingerprint("slice.in", a)
    assert fingerprint("kotak.com", a) != fingerprint("kotak.com", "Card blocked due to suspicious activity")


def test_fingerprint_normalizes_reply_prefixes_and_ids():
    assert normalize_subject("Re: Fwd: Order #40213 shipped") == normalize_subject("Order #99 shipped")
    assert normalize_subject("Your OTP 4821 for ref AB12CD34") == normalize_subject("Your OTP 9902 for ref ZX98QW11")


# ---- heuristics ----------------------------------------------------------------------------

def meta(labels=("INBOX",), **headers):
    return parse_metadata(gmail_msg({"From": headers.pop("From", "x@shop.com"), "Subject": "s", **headers}, labels=labels))


def test_heuristics():
    assert suggest(meta(labels=("INBOX", "CATEGORY_PROMOTIONS"))).strength == "strong"
    assert suggest(meta(**{"List-Unsubscribe": "<mailto:u@x>"})).strength == "weak"
    assert suggest(meta(From="noreply@hirepro.in")).strength == "weak"
    assert suggest(meta(From="priya@globex.com")) is None


# ---- mailing lists (ARC) ----------------------------------------------------------------------
# Real-world shape: a placement cell mails through a Google Groups list. Top-level DKIM/SPF pass
# for googlegroups.com; the author's own pes.edu results arrive inside Gmail's arc=pass summary.
GROUPS_RESULT = ("mx.google.com;       dkim=pass header.i=@googlegroups.com header.s=20251104 header.b=q/hi+jOu;       "
                 "arc=pass (i=3 spf=pass spfdomain=pes.edu dkim=pass dkdomain=pes.edu dmarc=pass fromdomain=pes.edu);       "
                 "spf=pass (google.com: domain of placement_cse_2027+bnc@googlegroups.com designates 209.85.220.55 as permitted sender) "
                 "smtp.mailfrom=placement_cse_2027+bnc@googlegroups.com")


def seal(i, d):
    return f"i={i}; a=rsa-sha256; t=1761300000; cv=pass; d={d}; s=arc-20240605; b=abc"


def test_mailing_list_mail_is_verified_through_a_google_sealed_arc_set():
    assert authenticated_domain([GROUPS_RESULT], "pes.edu", [seal(4, "google.com"), seal(3, "google.com"), seal(2, "google.com")]) == "pes.edu"


@pytest.mark.parametrize("seals", [
    [seal(3, "evil.example")],  # anyone can seal fabricated results with their own domain
    [seal(2, "google.com")],    # the summarised set (i=3) is not Google's
    [],                          # no ARC-Seal at all
])
def test_arc_results_from_untrusted_sealers_are_ignored(seals):
    assert authenticated_domain([GROUPS_RESULT], "pes.edu", seals) is None


def test_arc_fail_or_misaligned_author_is_not_verified():
    failed = GROUPS_RESULT.replace("arc=pass", "arc=fail")
    assert authenticated_domain([failed], "pes.edu", [seal(3, "google.com")]) is None
    assert authenticated_domain([GROUPS_RESULT], "kotak.com", [seal(3, "google.com")]) is None


def test_parse_metadata_reads_arc_seals():
    m = parse_metadata(gmail_msg({"From": "PESU placements <pesuplacements@pes.edu>", "Subject": "Drive",
                                   "ARC-Seal": seal(3, "google.com")}, auth=[GROUPS_RESULT]))
    assert m.authenticated_domain == "pes.edu"
