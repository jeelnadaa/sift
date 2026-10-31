"""Reader document theme: dark by default to match the app, original colours on request."""
from app import reader


def test_plain_mail_gets_app_colours_and_font():
    doc = reader.document("<p>Hello</p>")
    assert "background:#151518" in doc and "Satoshi" in doc
    assert 'id="sift-mail"' not in doc


def test_mail_with_own_colours_is_inverted_with_pictures_restored():
    doc = reader.document('<table bgcolor="#ffffff"><tr><td style="color:#333">Hi</td></tr></table>')
    assert 'id="sift-mail"' in doc and "invert(1)" in doc
    assert "#sift-mail img" in doc


def test_original_colours_on_request():
    doc = reader.document('<p style="color:#333">Hi</p>', "original")
    assert "background:#fff" in doc and 'id="sift-mail"' not in doc


def test_own_colour_detection():
    assert reader.has_own_colors('<div style="background-color: red">')
    assert reader.has_own_colors('<font color="red">x</font>')
    assert not reader.has_own_colors('<div style="border-color: red; font-size: 12px">x</div>')


def test_font_policy_allows_only_self():
    assert "font-src 'self' data:" in reader.RENDER_CSP


def test_setting_ranges(db):
    import pytest
    from app import user_settings
    from app.models import User
    user = User(email="owner@gmail.com")
    db.add(user)
    db.flush()
    assert user_settings.update(db, user.id, {"daily_token_cap": 120000})["daily_token_cap"] == 120000
    for bad in ({"daily_token_cap": -5}, {"resend_limit": 99}, {"load_remote_images": "yes"}):
        with pytest.raises(ValueError):
            user_settings.update(db, user.id, bad)


def test_document_carries_its_own_policy_for_downloaded_copies():
    doc = reader.document("<p>Hi</p>")
    assert "http-equiv=\"Content-Security-Policy\"" in doc and "default-src 'none'" in doc and "script" not in doc
