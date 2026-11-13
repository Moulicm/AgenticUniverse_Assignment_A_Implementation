from __future__ import annotations

import base64
import hashlib
import hmac

from cryptography.fernet import Fernet


class PIIProtector:
    def __init__(self, secret: bytes):
        # Accept a Fernet key directly; otherwise derive a valid Fernet key.
        try:
            self.fernet = Fernet(secret)
            material = secret
        except Exception:
            material = hashlib.sha256(secret).digest()
            self.fernet = Fernet(base64.urlsafe_b64encode(material))
        self._hmac_key = hmac.new(material, b"agentic-ledger-phone-index", hashlib.sha256).digest()

    def encrypt(self, value: str) -> str:
        return self.fernet.encrypt(value.encode("utf-8")).decode("ascii")

    def decrypt(self, value: str) -> str:
        return self.fernet.decrypt(value.encode("ascii")).decode("utf-8")

    def phone_digest(self, canonical_phone: str) -> str:
        return hmac.new(self._hmac_key, canonical_phone.encode("utf-8"), hashlib.sha256).hexdigest()
