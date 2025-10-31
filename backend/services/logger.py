import logging
from ..config import get_log_level, is_prod, mask_sensitive_data
import re

class SensitiveDataFilter(logging.Filter):
    """Filter to mask sensitive data in production environment"""
    def filter(self, record):
        if is_prod():
            # Apply masking to the message
            if isinstance(record.msg, dict):
                # If the message is a dictionary, mask sensitive values
                record.msg = mask_sensitive_data(record.msg)
            else:
                # Check if the message contains variable assignments with sensitive names
                # Pattern to match variable names containing KEY, SECRET, or TOKEN followed by assignment
                msg_str = str(record.msg)
                # Mask values for variables with sensitive names in log messages
                # This handles cases like "API_KEY=abc123" or "SECRET_TOKEN=xyz789"
                sensitive_pattern = r'\b(\w*?(?:KEY|SECRET|TOKEN)\w*?\s*[=:]?\s*)([^\s,;]+)'
                record.msg = re.sub(sensitive_pattern, r'\1***', msg_str, flags=re.IGNORECASE)
        return True

log = logging.getLogger("reputonbot")
# базовая конфигурация, если её нет
if not log.handlers:
    log.setLevel(get_log_level())
    h = logging.StreamHandler()
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    h.setFormatter(fmt)
    h.addFilter(SensitiveDataFilter())
    log.addHandler(h)

__all__ = ["log"]
