import logging, json, time, os
from typing import Any, Dict, Optional
from fastapi import Request

LOGGER = logging.getLogger("reputonbot")  # <- фиксированное имя

# Get app version from config or environment
APP_VERSION = os.getenv("APP_VERSION", "unknown")

def log_event(event: str, **fields) -> None:
    """
    Log an event in JSON format with default fields.
    
    Args:
        event: Event name
        **fields: Additional fields to include in the log
    """
    # Add default fields
    log_data = {
        "event": event,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "app_version": APP_VERSION
    }
    
    # Add provided fields, masking sensitive ones
    for key, value in fields.items():
        if key.lower().endswith(('key', 'token', 'secret')):
            log_data[key] = "***"
        else:
            log_data[key] = value
    
    # Log as JSON string
    json_string = json.dumps(log_data, ensure_ascii=False)
    LOGGER.info(json_string)


def get_ms(request: Request) -> tuple[float, float, float]:
    """
    Get timing measurements from request state.
    
    Returns:
        tuple: (elapsed_ms, db_ms, llm_ms)
    """
    # Calculate elapsed time if start time is available
    elapsed_ms = 0.0
    if hasattr(request.state, 'start_time'):
        elapsed_ms = (time.perf_counter() - request.state.start_time) * 1000
    
    # Get DB and LLM timing from request state, defaulting to 0 if not set
    db_ms = getattr(request.state, 'db_ms', 0.0)
    llm_ms = getattr(request.state, 'llm_ms', 0.0)
    
    return elapsed_ms, db_ms, llm_ms


def add_db_ms(request: Request, delta_ms: float) -> None:
    """
    Add DB timing to request state.
    
    Args:
        request: FastAPI request object
        delta_ms: Time to add in milliseconds
    """
    if not hasattr(request.state, 'db_ms'):
        request.state.db_ms = 0.0
    request.state.db_ms += delta_ms


def add_llm_ms(request: Request, delta_ms: float) -> None:
    """
    Add LLM timing to request state.
    
    Args:
        request: FastAPI request object
        delta_ms: Time to add in milliseconds
    """
    if not hasattr(request.state, 'llm_ms'):
        request.state.llm_ms = 0.0
    request.state.llm_ms += delta_ms