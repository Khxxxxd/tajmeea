"""Errors the user sees, always in plain Kuwaiti Arabic."""
from __future__ import annotations

import asyncio
import errno


class UserError(Exception):
    """A problem we can explain to the user. `code` lets the interface react (e.g. go back to the key step)."""

    def __init__(self, message: str, code: str = "error"):
        super().__init__(message)
        self.code = code


OFFLINE = "ما قدرنا نوصل لتيليجرام. تأكد إن النت شغال وجرّب مرة ثانية."


def friendly(exc: BaseException) -> UserError:
    if isinstance(exc, UserError):
        return exc
    name = type(exc).__name__
    seconds = getattr(exc, "seconds", None)
    table = {
        "ApiIdInvalidError": ("المفتاح غلط. ارجع لصفحة تيليجرام وانسخها كاملة مرة ثانية.", "bad_key"),
        "ApiIdPublishedFloodError": ("هذا المفتاح منشور ومحظور من تيليجرام. سوّ مفتاح جديد.", "bad_key"),
        "PhoneNumberInvalidError": ("الرقم مو صحيح. اكتبه كامل مع مفتاح الدولة، مثل ‎+965…", "error"),
        "PhoneNumberBannedError": ("تيليجرام حاظر هالرقم.", "error"),
        "PhoneCodeInvalidError": ("الكود غلط. تأكد منه وجرّب مرة ثانية.", "error"),
        "PhoneCodeExpiredError": ("الكود انتهى. اطلب كود جديد.", "error"),
        "PasswordHashInvalidError": ("كلمة السر غلط.", "error"),
        "UsernameNotOccupiedError": ("ما لقينا قناة بهالاسم. تأكد من الرابط.", "not_found"),
        "UsernameInvalidError": ("ما لقينا قناة بهالاسم. تأكد من الرابط.", "not_found"),
        "ChannelPrivateError": ("هذي القناة خاصة أو انحذفت. تجميعة تشتغل مع القنوات العامة بس.", "private"),
        "ChannelInvalidError": ("ما قدرنا نفتح هالقناة.", "not_found"),
        "AuthKeyUnregisteredError": ("انتهت جلستك. ادخل مرة ثانية.", "logged_out"),
        "SessionRevokedError": ("انتهت جلستك. ادخل مرة ثانية.", "logged_out"),
        "UserDeactivatedError": ("حسابك موقوف من تيليجرام.", "logged_out"),
    }
    if name in table:
        message, code = table[name]
        return UserError(message, code)
    if name == "FloodWaitError" and seconds:
        minutes = max(1, round(seconds / 60))
        return UserError(f"تيليجرام طلب ننطر تقريباً {minutes} دقيقة قبل نكمل.", "flood")
    if isinstance(exc, (ConnectionError, asyncio.TimeoutError, TimeoutError)):
        return UserError(OFFLINE, "offline")
    if isinstance(exc, OSError) and exc.errno == errno.ENOSPC:
        return UserError("المساحة خلصت بجهازك. فضّي شوي وكمّل.", "disk_full")
    if isinstance(exc, OSError) and exc.errno in (errno.EACCES, errno.EPERM):
        return UserError("ما عندنا صلاحية نكتب بهالمجلد. اختر مجلد ثاني.", "folder")
    return UserError("صار خطأ ما توقعناه. جرّب مرة ثانية، وإذا تكرر أرسل لنا سجل الأخطاء.", "unexpected")
