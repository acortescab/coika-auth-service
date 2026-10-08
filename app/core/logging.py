# app/core/logging.py
import json
import logging
import logging.config
from datetime import datetime, timezone

_STANDARD_ATTRS = set(vars(logging.makeLogRecord({}))) | {"message", "asctime", "taskName"}

def setup_logging(level: str = "INFO") -> None:
    """
    Configures the logging configuration for the application.
    """
    logging.config.dictConfig({
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {"json": {"()": "app.core.logging.JSONFormatter"}},
        "handlers": {
            "stdout": {
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stdout",
                "formatter": "json",
            }
        },
        "root": {"level": level, "handlers": ["stdout"]},
        "loggers": {
            "uvicorn": {"handlers": [], "propagate": True},
            "uvicorn.error": {"handlers": [], "propagate": True},
            "uvicorn.access": {"handlers": [], "propagate": True},
        },
    })

class JSONFormatter(logging.Formatter):
    """
    A JSON formatter that formats log records as JSON.
    """
    def format(self, record: logging.LogRecord) -> str:
        """
        Format a log record as JSON.
        """
        log = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage()
        }

        for key, value in vars(record).items():
            if key not in _STANDARD_ATTRS:
                log[key] = value
        if record.exc_info:
            log["exception"] = self.formatException(record.exc_info)
        return json.dumps(log, default=str, ensure_ascii=False)