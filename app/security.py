from __future__ import annotations
import base64
import hashlib
import hmac
import secrets
from dataclasses import dataclass

ITERATIONS = 310_000
ROLES = {
    "admin": "مدير النظام",
    "president": "رئيس الجمعية",
    "treasurer": "أمين المال",
    "reader": "قارئ العدادات",
    "reception": "موظف الاستقبال",
    "auditor": "المدقق",
}

PERMISSIONS = {
    "admin": {"*"},
    "president": {"view", "export", "print", "readings.approve", "invoices.issue", "reports.view", "complaints.view", "members.view"},
    "treasurer": {"view", "export", "print", "members.view", "readings.view", "tariffs.manage", "invoices.manage", "invoices.issue", "payments.manage", "finance.manage", "debts.manage", "reports.view"},
    "reader": {"view", "readings.view", "readings.manage", "members.view"},
    "reception": {"view", "print", "members.view", "members.manage", "complaints.view", "complaints.manage", "readings.view"},
    "auditor": {"view", "export", "print", "reports.view", "audit.view", "members.view", "readings.view", "complaints.view"},
}

@dataclass
class User:
    id: int
    username: str
    full_name: str
    role: str
    active: bool = True

    def can(self, permission: str) -> bool:
        granted = PERMISSIONS.get(self.role, set())
        return "*" in granted or permission in granted


def hash_password(password: str, salt: bytes | None = None) -> str:
    if len(password) < 8:
        raise ValueError("كلمة المرور يجب أن تتكون من 8 أحرف على الأقل.")
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, ITERATIONS)
    return f"pbkdf2_sha256${ITERATIONS}${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations, salt, expected = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), base64.b64decode(salt), int(iterations))
        return hmac.compare_digest(actual, base64.b64decode(expected))
    except (ValueError, TypeError):
        return False


def new_totp_like_token() -> str:
    """Random token used for backup integrity metadata, not authentication."""
    return secrets.token_urlsafe(32)
