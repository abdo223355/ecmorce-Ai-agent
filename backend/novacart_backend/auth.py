"""Login + JWT signing for the NovaCart backend.

The Gateway verifies tokens locally with the public key from /.well-known/jwks.json (Phase 3 D24).
Claims: sub (customer_id / worker_id), role, sid (login session id), iat, exp, kid in the header.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import time
import uuid
from pathlib import Path

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

TOKEN_TTL_SECONDS = int(os.getenv("TOKEN_TTL_SECONDS", "1800"))  # design choice: 30 min
ISSUER = "novacart-backend"


class KeyStore:
    """Holds one RSA signing key. Created on first start and kept in KEY_DIR."""

    def __init__(self, key_dir: str | Path):
        self.key_dir = Path(key_dir)
        self.key_dir.mkdir(parents=True, exist_ok=True)
        pem_path = self.key_dir / "signing_key.pem"
        if pem_path.exists():
            self.private_key = serialization.load_pem_private_key(pem_path.read_bytes(), password=None)
        else:
            self.private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            pem_path.write_bytes(
                self.private_key.private_bytes(
                    serialization.Encoding.PEM,
                    serialization.PrivateFormat.PKCS8,
                    serialization.NoEncryption(),
                )
            )
            os.chmod(pem_path, 0o600)
        pub = self.private_key.public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
        )
        self.kid = hashlib.sha256(pub).hexdigest()[:16]

    def jwks(self) -> dict:
        numbers = self.private_key.public_key().public_numbers()

        def b64(n: int) -> str:
            raw = n.to_bytes((n.bit_length() + 7) // 8, "big")
            return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

        return {"keys": [{"kty": "RSA", "use": "sig", "alg": "RS256", "kid": self.kid,
                          "n": b64(numbers.n), "e": b64(numbers.e)}]}

    def issue(self, subject_id: str, role: str) -> str:
        now = int(time.time())
        claims = {"sub": subject_id, "role": role, "sid": str(uuid.uuid4()),
                  "iss": ISSUER, "iat": now, "exp": now + TOKEN_TTL_SECONDS}
        return jwt.encode(claims, self.private_key, algorithm="RS256", headers={"kid": self.kid})

    def verify(self, token: str) -> dict:
        return jwt.decode(token, self.private_key.public_key(), algorithms=["RS256"], issuer=ISSUER)


# --- password hashing (PBKDF2, standard library only) ---
_ITER = 120_000


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _ITER)
    return f"pbkdf2${_ITER}${salt.hex()}${digest.hex()}"


def check_password(password: str, stored: str) -> bool:
    _, iters, salt_hex, digest_hex = stored.split("$")
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), int(iters))
    return hmac.compare_digest(digest.hex(), digest_hex)
