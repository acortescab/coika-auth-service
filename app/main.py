import logging
import os
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from slowapi.errors import RateLimitExceeded
from slowapi.extension import _rate_limit_exceeded_handler

from app.api.v0.routes import auth, health
from app.core.config import get_settings
from app.core.logging import setup_logging
from app.core.rate_limit import limiter
from app.core.telemetry import setup_telemetry
from app.db.session import engine_reader, engine_writer

setup_logging(get_settings().LOG_LEVEL)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan function to manage application startup and shutdown events.
    """
    logger.info("Starting application...")

    try:
        validate_settings(get_settings())
    except RuntimeError as e:
        logger.critical("settings validation failed, shutting down", extra={"error": str(e)})
        sys.exit(1)
        
    yield 
    logger.info("Closing application resources...")
    await engine_writer.dispose()
    await engine_reader.dispose()
    

def validate_settings(settings):
    """
    Validates the application settings. Raises a RuntimeError if any required settings are missing or invalid.
    Args: settings (Settings): The application settings to validate.
    """
    if not settings.SECRET_KEY or settings.SECRET_KEY == "":
        raise RuntimeError("SECRET KEY IS NULL")
    if not os.getenv("DATABASE_URL_READER"):
        raise RuntimeError("DATABASE_URL_READER missing")
    if not os.getenv("DATABASE_URL_WRITER"):
        raise RuntimeError("DATABASE_URL_WRITER missing")

app = FastAPI(lifespan=lifespan)
app.include_router(health.router, prefix="/v0")
app.include_router(auth.router, prefix="/v0")
setup_telemetry(app, get_settings())
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

@app.get("/.well-known/jwks.json")
def jwks():
    """
    Expose the public key set so external services can validate JWTs.
    """
    settings = get_settings()
    return settings.jwks


@app.get("/")
def root():
    """
    Root endpoint for the OAuth service.
    """
    settings = get_settings()
    return {"status": "ok", "service": "OAuth", "env": settings.ENV}
