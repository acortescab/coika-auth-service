# app/core/telemetry.py
import logging

from fastapi import FastAPI
from opentelemetry import metrics, trace
from opentelemetry._logs import set_logger_provider
from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.logging import LoggingInstrumentor
from opentelemetry.instrumentation.logging.handler import LoggingHandler
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from app.core.config import Settings
from app.db.session import engine_reader, engine_writer

logger = logging.getLogger(__name__)

def setup_telemetry(app: FastAPI, settings: Settings) -> None:
    """
    Configures OpenTelemetry traces, metrics and logs and exports them over OTLP/gRPC.
    Does nothing when OTEL_EXPORTER_OTLP_ENDPOINT is empty, so environments without a collector are unaffected.
    """
    endpoint = settings.OTEL_EXPORTER_OTLP_ENDPOINT

    if not endpoint:
        logger.info("telemetry disabled, OTEL_EXPORTER_OTLP_ENDPOINT is not set")
        return

    resource = Resource.create({
        "service.name": settings.OTEL_SERVICE_NAME,
        "deployment.environment": settings.ENV,
    })

    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
    trace.set_tracer_provider(tracer_provider)

    meter_provider = MeterProvider(
        resource=resource,
        metric_readers=[PeriodicExportingMetricReader(OTLPMetricExporter(endpoint=endpoint))],
    )
    metrics.set_meter_provider(meter_provider)

    logger_provider = LoggerProvider(resource=resource)
    logger_provider.add_log_record_processor(BatchLogRecordProcessor(OTLPLogExporter(endpoint=endpoint)))
    set_logger_provider(logger_provider)
    # Ships every log record to the collector; the stdout JSON handler from setup_logging keeps working.
    logging.getLogger().addHandler(LoggingHandler(level=logging.NOTSET, logger_provider=logger_provider))

    # Adds otelTraceID / otelSpanID to every LogRecord; JSONFormatter prints them as extra fields on stdout.
    # The instrumentor's own OTLP handler is disabled because the one above already ships the logs.
    LoggingInstrumentor().instrument(
        set_logging_format=False, inject_trace_context=True, enable_log_auto_instrumentation=False
    )
    FastAPIInstrumentor.instrument_app(app, excluded_urls="health")
    # skip_dep_check: the instrumentor declares support for sqlalchemy < 2.1 but we run 2.1.x; without this it
    # refuses to instrument and no SQL spans are produced. Remove once the instrumentor supports 2.1.
    SQLAlchemyInstrumentor().instrument(engines=[engine_writer.sync_engine, engine_reader.sync_engine], skip_dep_check=True)

    logger.info("telemetry enabled", extra={"otlp_endpoint": endpoint, "service": settings.OTEL_SERVICE_NAME})
