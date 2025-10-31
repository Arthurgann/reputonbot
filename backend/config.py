from dotenv import load_dotenv
import os, re, logging

# Load environment-specific .env file
APP_ENV = os.getenv("APP_ENV", "dev").lower()
env_file = ".env.prod" if APP_ENV == "prod" else ".env.local"
load_dotenv(env_file)  # Load environment-specific file first
load_dotenv(".env", override=False)  # Fallback to default .env if variables not found

try:
    import re, os
    _host = None
    if os.getenv("SUPABASE_URL"):
        m = re.search(r"https?://([^/]+)/", os.getenv("SUPABASE_URL"))
        _host = m.group(1) if m else os.getenv("SUPABASE_URL")
    print(f"[CONFIG] APP_ENV={APP_ENV} dotenv={env_file} supabase_host={_host}")
except Exception:
    pass

class Settings:
    APP_ENV = os.getenv("APP_ENV", "dev")
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    APP_VERSION = os.getenv("APP_VERSION", "dev")

    SUPABASE_URL = os.getenv("SUPABASE_URL", "")
    SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY", "")
    SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")

    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

settings = Settings()

# Extract supabase host and log connection info
supabase_url = settings.SUPABASE_URL
if supabase_url:
    supabase_host_match = re.search(r'https?://([^/]+)', supabase_url)
    supabase_host = supabase_host_match.group(1) if supabase_host_match else supabase_url
else:
    supabase_host = ""

logging.info("config: APP_ENV=%s dotenv=%s supabase_host=%s", APP_ENV, env_file, supabase_host)


def is_prod():
    """Check if running in production environment"""
    return os.getenv("APP_ENV", "dev").lower() == 'prod'


def get_log_level():
    """Get appropriate log level based on environment"""
    if is_prod():
        return logging.INFO
    return getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper())


def mask_sensitive_data(data):
    """Mask sensitive data in logs if in production"""
    if not is_prod():
        return data

    # Convert to string to check for sensitive patterns
    if isinstance(data, dict):
        masked_data = {}
        for key, value in data.items():
            if isinstance(key, str) and any(pattern in key.upper() for pattern in ['KEY', 'SECRET', 'TOKEN']):
                masked_data[key] = '***'
            else:
                masked_data[key] = mask_sensitive_data(value)
        return masked_data
    elif isinstance(data, str):
        # For string values, return as is since they are not variable names
        return data
    elif isinstance(data, (int, float, bool, type(None))):
        # For primitive types, return as is
        return data
    else:
        # For other types, recursively apply masking if it's a container
        return data
