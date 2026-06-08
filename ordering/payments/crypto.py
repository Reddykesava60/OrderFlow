import base64
import hashlib
import json

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings


def _fernet(secret):
    digest = hashlib.sha256(f"{secret}:dineflow-payments-v1".encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def _payment_encryption_key():
    return getattr(settings, "PAYMENT_ENCRYPTION_KEY", "") or settings.SECRET_KEY


def encrypt_text(value):
    return _fernet(_payment_encryption_key()).encrypt((value or "").encode("utf-8")).decode("utf-8")


def decrypt_text(value):
    if not value:
        return ""
    encrypted = value.encode("utf-8")
    keys = [_payment_encryption_key()]
    if settings.SECRET_KEY not in keys:
        keys.append(settings.SECRET_KEY)
    for key in keys:
        try:
            return _fernet(key).decrypt(encrypted).decode("utf-8")
        except InvalidToken:
            continue
    return ""


def encrypt_json(value):
    return encrypt_text(json.dumps(value or {}, separators=(",", ":"), sort_keys=True))


def decrypt_json(value):
    raw = decrypt_text(value)
    if not raw:
        return {}
    return json.loads(raw)
