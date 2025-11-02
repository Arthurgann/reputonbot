import logging
import os
import json

log = logging.getLogger("reputonbot")

# Check if JSON logging is enabled
LOG_JSON = os.getenv("LOG_JSON", "0") == "1"

class JSONFormatter(logging.Formatter):
    """Custom formatter to output logs as JSON when LOG_JSON is enabled"""
    def format(self, record):
        log_data = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # Add timestamp if available in record
        if hasattr(record, 'asctime'):
            log_data["timestamp"] = record.asctime
        # Add any extra fields that were passed
        for key, value in record.__dict__.items():
            if key not in ['name', 'msg', 'args', 'levelname', 'levelno', 'pathname', 'filename', 'module', 'lineno', 'funcName', 'created', 'msecs', 'relativeCreated', 'thread', 'threadName', 'processName', 'process', 'getMessage', 'asctime']:
                log_data[key] = value
        return json.dumps(log_data, ensure_ascii=False)

# базовая конфигурация, если её нет
if not log.handlers:
    log.setLevel(logging.INFO)
    h = logging.StreamHandler()
    if LOG_JSON:
        fmt = JSONFormatter()
    else:
        fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    h.setFormatter(fmt)
    log.addHandler(h)

__all__ = ["log"]
