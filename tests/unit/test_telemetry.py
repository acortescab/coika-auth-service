from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI

from app.core.telemetry import setup_telemetry


def test_setup_telemetry_does_nothing_without_an_otlp_endpoint():
    """
    Environments without a collector (CI, prod until the observability host exists) must run untouched:
    no providers are registered and nothing is instrumented.
    """
    settings = SimpleNamespace(OTEL_EXPORTER_OTLP_ENDPOINT="", OTEL_SERVICE_NAME="auth-service", ENV="test")

    with patch("app.core.telemetry.trace") as trace_module, \
         patch("app.core.telemetry.FastAPIInstrumentor") as fastapi_instrumentor, \
         patch("app.core.telemetry.SQLAlchemyInstrumentor") as sqlalchemy_instrumentor:
        setup_telemetry(FastAPI(), settings)

    trace_module.set_tracer_provider.assert_not_called()
    fastapi_instrumentor.instrument_app.assert_not_called()
    sqlalchemy_instrumentor.assert_not_called()
