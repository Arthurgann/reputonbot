from typing import Optional, Any, Dict
from supabase import create_client, Client
from .logger import log
from ..config import settings
import asyncio

_client: Optional[Client] = None
_platform_rules_cache: Optional[Dict[str, Dict[str, Any]]] = None
_cache_lock = asyncio.Lock()

def get_client() -> Client:
    global _client
    if _client is None:
        if not settings.SUPABASE_URL or not settings.SUPABASE_SERVICE_ROLE_KEY:
            raise RuntimeError("Supabase credentials are missing in .env")
        _client = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)
    return _client

async def preload_platform_rules() -> None:
    """Preload all platform rules into memory cache"""
    global _platform_rules_cache
    async with _cache_lock:
        sb = get_client()
        res = sb.table("platform_rules").select("platform, name, rules, instruction_template, tips, report_url, system_prompt, rules_version").execute()
        _platform_rules_cache = {}
        for row in res.data if res and res.data else []:
            platform_data = {
                "platform": row["platform"],
                "name": row.get("name") or row["platform"],
                "rules": row.get("rules") or {},
                "instruction_template": row.get("instruction_template") or "",
                "tips": row.get("tips") or [],
                "report_url": row.get("report_url") or "",
                "system_prompt": row.get("system_prompt") or "",
                "rules_version": row.get("rules_version") or "",
            }
            _platform_rules_cache[row["platform"]] = platform_data
        print(f"Preloaded {len(_platform_rules_cache)} platform rules into cache")

async def refresh_platform_rules_cache() -> None:
    """Refresh platform rules cache periodically"""
    await preload_platform_rules()

def get_platform_rules_cached(platform: str) -> Dict[str, Any]:
    """Get platform rules from cache (fast)"""
    if _platform_rules_cache is None:
        raise RuntimeError("Platform rules cache not initialized. Call preload_platform_rules() first.")
    if platform not in _platform_rules_cache:
        raise ValueError(f"No rules for platform={platform}")
    return _platform_rules_cache[platform]

def get_platform_prompt(platform: str) -> str:
    sb = get_client()
    res = sb.table("platform_rules").select("system_prompt").eq("platform", platform).single().execute()
    data = res.data if res else None
    if not data or "system_prompt" not in data:
        raise ValueError(f"No system_prompt for platform={platform}")
    return data["system_prompt"]

def get_platform_rules(platform: str) -> Dict[str, Any]:
    sb = get_client()
    res = sb.table("platform_rules").select("platform, name, rules, instruction_template, tips, report_url, system_prompt, rules_version").eq("platform", platform).single().execute()
    row = res.data if res else None
    if not row:
        raise ValueError(f"No rules for platform={platform}")
    platform_data = {
        "platform": row["platform"],
        "name": row.get("name") or row["platform"],
        "rules": row.get("rules") or {},
        "instruction_template": row.get("instruction_template") or "",
        "tips": row.get("tips") or [],
        "report_url": row.get("report_url") or "",
        "system_prompt": row.get("system_prompt") or "",
        "rules_version": row.get("rules_version") or "",
    }
    return platform_data

def log_interaction(tg_user_id: Optional[str], platform: str, input_text: str, output_json: Dict[str, Any], chat_id: Optional[str] = None) -> None:
    sb = get_client()
    # Use chat_id if provided, otherwise fall back to tg_user_id if it's numeric
    final_chat_id = chat_id if chat_id is not None else (tg_user_id if tg_user_id and tg_user_id.isdigit() else None)
    _ = sb.table("interactions").insert({
        "tg_user_id": tg_user_id,
        "chat_id": final_chat_id,
        "platform": platform,
        "input_text": input_text,
        "output_json": output_json
    }).execute()

    # Note: Rate limiting counter is incremented here via database insertion
    # The count_interactions_by_chat_id function counts today's records

def set_chat_state(chat_id: int, platform: str) -> None:
    """
    Save or update chat state with selected platform
    """
    import datetime
    sb = get_client()
    _ = sb.table("chat_state").upsert({
        "chat_id": chat_id,
        "platform": platform,
        "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
    }).execute()

def get_platform_from_chat_state(chat_id: int) -> Optional[str]:
    """
    Get platform from chat state
    """
    sb = get_client()
    res = sb.table("chat_state").select("platform").eq("chat_id", chat_id).single().execute()
    data = res.data if res else None
    if not data or "platform" not in data:
        return None
    return data["platform"]

def get_chat_state_with_updated_at(chat_id: int) -> Optional[Dict[str, Any]]:
    """
    Get chat state with updated_at for TTL check (optimized query)
    """
    sb = get_client()
    res = sb.table("chat_state").select("platform, updated_at").eq("chat_id", chat_id).maybe_single().execute()
    return res.data if res else None

def count_interactions_by_chat_id(chat_id: int) -> int:
    """
    Count interactions for a specific chat_id to implement rate limiting
    Counts only today's interactions (UTC day)
    """
    import datetime as dt
    sb = get_client()
    today_utc = dt.datetime.now(dt.timezone.utc).date().isoformat()
    start_of_day = f"{today_utc}T00:00:00+00:00"
    end_of_day = f"{today_utc}T23:59:59+00:00"

    res = sb.table("interactions").select("*", count="exact") \
        .eq("chat_id", chat_id) \
        .gte("created_at", start_of_day) \
        .lte("created_at", end_of_day) \
        .execute()
    return res.count or 0

def check_rate_limit(chat_id: int, utc_day: str, threshold: int = 10) -> tuple[int, bool]:
    """
    Check rate limit for chat_id on utc_day.
    Returns (hits_before, allowed) where allowed is True if hits_before < threshold.
    Does not increment the counter.
    """
    sb = get_client()
    res = sb.table("rate_limits").select("hits").eq("chat_id", chat_id).eq("utc_day", utc_day).maybe_single().execute()
    if res and res.data:
        hits = res.data["hits"]
        return hits, hits < threshold
    else:
        return 0, True

def increment_rate_limit(chat_id: int, utc_day: str, threshold: int = 10) -> bool:
    """
    Atomically increment rate limit for chat_id on utc_day.
    Returns True if increment was successful (hits <= threshold), False otherwise.
    """
    sb = get_client()
    try:
        res = sb.rpc("increment_rate_limit", {"p_chat_id": chat_id, "p_utc_day": utc_day, "p_threshold": threshold}).execute()
        return res.data[0] if res and res.data else False
    except Exception as e:
        log.warning(f"Failed to increment rate limit: {e}")
        return False

def get_cached_request(chat_id: int, utc_day: str, request_id: str) -> Optional[Dict[str, Any]]:
    """
    Get cached response for idempotency check.
    Returns dict with 'response' and 'status' if found, None otherwise.
    """
    sb = get_client()
    try:
        # Try the standard query first
        res = sb.table("request_cache").select("response, status").eq("chat_id", chat_id).eq("utc_day", utc_day).eq("request_id", request_id).execute()
        if res and res.data and len(res.data) > 0:
            return res.data[0]
        return None
    except Exception as e:
        log.warning(f"Failed to get cached request: {e}")
        return None

def cache_request(chat_id: int, utc_day: str, request_id: str, response: Dict[str, Any], status: int) -> None:
    """
    Cache response for idempotency.
    """
    sb = get_client()
    try:
        sb.table("request_cache").upsert({
            "chat_id": chat_id,
            "utc_day": utc_day,
            "request_id": request_id,
            "response": response,
            "status": status
        }).execute()
    except Exception as e:
        log.warning(f"Failed to cache request: {e}")

def check_and_increment_rate_limit(chat_id: int, threshold: int = 10) -> bool:
    """
    Check if chat_id has exceeded rate limit for today (UTC).
    Returns True if allowed, False if limit exceeded.
    Only increments counter on successful check.
    """
    import datetime as dt
    sb = get_client()
    today_utc = dt.datetime.now(dt.timezone.utc).date().isoformat()

    # Count current interactions for today
    current_count = count_interactions_by_chat_id(chat_id)

    if current_count >= threshold:
        return False

    # If under limit, we'll increment only after successful composition
    # For now, just return True - actual increment happens in log_interaction
    return True