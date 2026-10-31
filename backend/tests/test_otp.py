"""One-time codes: real-world shapes are found, look-alike numbers are not."""
import pytest

from app import otp

FOUND = [
    ("Your Google verification code", "Your Google verification code is 482913. Don't share it.", "482913"),
    ("Microsoft account security code", "Please use the following security code for the Microsoft account jo**@gmail.com.\nSecurity code: 7314805", "7314805"),
    ("Amazon.in: Your one-time password", "Your One-Time Password (OTP) is 618204. Do not share it with anyone.", "618204"),
    ("OTP for transaction", "OTP for txn of INR 2,500.00 at AMAZON on card XX1234 is 482913. Valid for 10 mins. Do not share with anyone.", "482913"),
    ("HDFC Bank NetBanking", "Dear Customer, 731042 is the One Time Password for your NetBanking login. Valid till 10:42. Never share your OTP.", "731042"),
    ("Swiggy login", "Your OTP for Swiggy login is 5521. It expires in 10 minutes.", "5521"),
    ("Zomato", "Use OTP 384 920 to sign in to Zomato.", "384920"),
    ("Placement portal: verify your email", "Hi Jeel,\nYour verification code for the placement portal is: 7H3K9Q\nIt expires in 15 minutes.", "7H3K9Q"),
    ("Sign in to GitHub", "Here is your GitHub launch code: 41275093\nIf you didn't try to sign in, change your password.", "41275093"),  # a bare "code:" counts
    ("Your sign-in code", "Your sign-in code is 9921-4410", "99214410"),
    ("Login attempt", "Your code: 552910", "552910"),
    ("Verify your account", "Enter this passcode to continue: 640218", "640218"),
    ("Two-step verification", "Your two-step verification code is 204861.", "204861"),
]

NOT_FOUND = [
    ("Rs 2,500 debited", "Rs 2,500.00 debited from a/c XX1234 on 12-05-26 to VPA abc@okicici. Not you? Call 18002586161."),
    ("Your order has shipped", "Order #403-1234567-1234567 is on its way. Tracking number 785412369852."),
    ("Invoice 2026-10", "Invoice no 48213 for October 2026. Amount due INR 1499."),
    ("Weekend sale", "Use promo code SAVE2026 for 20% off. Coupon code: 482913 works too."),
    ("Address update", "Your pincode: 400001 has been updated. PIN code: 560034."),
    ("Meeting at 1830", "See you at 1830 in room 204. Call me on 9876543210."),
    ("Monthly statement", "Your statement for 2026 is ready. Balance: 48213."),
    ("Security alert", "We noticed a new sign-in to your account on 31 Oct 2026 at 10:42. If this was you, ignore this mail."),
    ("Hello", "Just a plain mail with 482913 in it and no code words."),
    ("", ""),
]


@pytest.mark.parametrize("subject,body,code", FOUND)
def test_codes_are_found(subject, body, code):
    assert otp.find(subject, body) == code


@pytest.mark.parametrize("subject,body", NOT_FOUND)
def test_look_alike_numbers_are_not_codes(subject, body):
    assert otp.find(subject, body) is None


def test_quick_check_spots_code_mail_only():
    assert otp.mentioned("Your OTP", "")
    assert otp.mentioned("Hello", "Your verification code is 1234")
    assert not otp.mentioned("Weekly newsletter", "Ten things to read this week")


def test_placeholders_and_years_are_not_codes():
    assert otp.find("Your OTP", "Your OTP is 000000") is None
    assert otp.find("Your OTP", "Your OTP is 2026") is None
