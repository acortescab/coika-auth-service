import base64
from functools import cached_property, lru_cache
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from dotenv import load_dotenv
from pydantic import ConfigDict, model_validator
from pydantic_settings import BaseSettings

# load .env file
load_dotenv()


def _base64url_encode(value: int) -> str:
    """Encode a big integer as a base64url string without padding."""
    raw = value.to_bytes((value.bit_length() + 7) // 8 or 1, byteorder="big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("utf-8")


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables or .env file.
    """
    model_config = ConfigDict(env_file=".env", extra="ignore")

    SECRET_KEY: str | None = None
    ALGORITHM: str = "RS256"
    ENV: str = "dev"
    LOG_LEVEL: str = "DEBUG"
    # Empty endpoint disables OpenTelemetry (e.g. prod until the observability host exists).
    OTEL_EXPORTER_OTLP_ENDPOINT: str = ""
    OTEL_SERVICE_NAME: str = "auth-service"

    @property
    def is_prod(self):
        """
        Checks if the application is running in the production environment.
        Returns: bool: True if the environment is "prod", False otherwise.
        """
        return self.ENV == "prod"

    @property
    def is_test(self):
        """
        Checks if the application is running in the test environment.
        Returns: bool: True if the environment is "test", False otherwise.
        """
        return self.ENV == "test"

    @property
    def is_dev(self):
        """
        Checks if the application is running in the development environment.
        Returns: bool: True if the environment is "dev", False otherwise.
        """
        return self.ENV == "dev"

    @cached_property
    def public_key_pem(self) -> str:
        """Return the matching RSA public key for the configured private key."""
        if not self.SECRET_KEY:
            raise ValueError("SECRET_KEY is not configured")

        private_key = serialization.load_pem_private_key(self.SECRET_KEY.encode("utf-8"), password=None)
        return private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode("utf-8")

    @property
    def jwks(self):
        """Build the JWKS document for the configured RSA key pair."""
        if not self.SECRET_KEY:
            raise ValueError("SECRET_KEY is not configured")

        private_key = serialization.load_pem_private_key(self.SECRET_KEY.encode("utf-8"), password=None)
        public_numbers = private_key.public_key().public_numbers()

        return {
            "keys": [
                {
                    "kty": "RSA",
                    "use": "sig",
                    "kid": "default",
                    "alg": self.ALGORITHM,
                    "n": _base64url_encode(public_numbers.n),
                    "e": _base64url_encode(public_numbers.e),
                }
            ]
        }

    @model_validator(mode="after")
    def load_secret_key(self):
        """
        Loads the secret key from a file if the environment is "dev".
        """
        if self.is_dev and not self.SECRET_KEY:
            self.SECRET_KEY = Path("secrets/private_key.pem").read_text()

        return self


@lru_cache
def get_settings():
    """
    Retrieves the application settings. 
    This function is cached to ensure that the settings are only loaded once during the application's lifetime.
    Returns: Settings: The application settings.
    """
    return Settings()
    