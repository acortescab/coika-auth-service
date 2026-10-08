import hashlib
import hmac
import secrets
from enum import Enum

import bcrypt
from fastapi.security import HTTPBearer
from opentelemetry import trace

tracer = trace.get_tracer(__name__)

class JWTAlgorithm(str, Enum):
    """
    Enum for Encryptation algorithm
    """
    HS256 = "HS256"
    HS384 = "HS384"
    HS512 = "HS512"
    
oauth2_scheme = HTTPBearer()

def hash_password(password: str) -> str:
    """
    Creates an encrypted hash for password
    """
    # bcrypt is CPU-bound and not covered by auto-instrumentation, so it needs its own span to show up in traces
    with tracer.start_as_current_span("bcrypt.hash_password"):
        return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verifies is the plain password matchs with the hashed one
    """
    with tracer.start_as_current_span("bcrypt.verify_password"):
        return bcrypt.checkpw(plain_password.encode(), hashed_password.encode())

# Verified against when a login email is unknown so response time does not reveal which emails exist
DUMMY_PASSWORD_HASH = hash_password("dummy-password-for-timing")

def generate_device_secret() -> str:
    """
    Creates a high-entropy secret that proves possession of a guest device
    """
    return secrets.token_urlsafe(32)

def hash_device_secret(secret: str) -> str:
    """
    Hashes a device secret. SHA-256 is enough because the secret is random and high-entropy,
    unlike a user-chosen password.
    """
    return hashlib.sha256(secret.encode()).hexdigest()

def verify_device_secret(secret: str, secret_hash: str) -> bool:
    """
    Constant-time check of a device secret against its stored hash
    """
    return hmac.compare_digest(hash_device_secret(secret), secret_hash)
