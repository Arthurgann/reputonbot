import time
import logging
from typing import Optional, Any, Dict
from supabase import create_client, Client
from .logger import log
from ..config import settings
import asyncio
from datetime import datetime, timezone

# Module-level Supabase client
sb: Client = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)

_client: Optional[Client] = None
_platform_rules_cache: Optional[Dict[str, Dict[str, Any]]] = None
_cache_lock = asyncio.Lock()

log = logging.getLogger("reputonbot")

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
        try:
            res = await asyncio.wait_for(
                asyncio.to_thread(lambda: sb.table("platform_rules").select("platform, name, rules, instruction_template, tips, report_url, system_prompt, rules_version").execute()),
                timeout=2.0
            )
        except asyncio.TimeoutError:
            log.warning("preload_platform_rules: Supabase query timed out")
            return
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

async def get_platform_prompt(platform: str) -> str:
    sb = get_client()
    t0 = time.perf_counter()
    try:
        res = await asyncio.wait_for(
            asyncio.to_thread(lambda: sb.table("platform_rules").select("system_prompt").eq("platform", platform).single().execute()),
            timeout=2.0
        )
    except asyncio.TimeoutError:
        log.warning(f"get_platform_prompt: Supabase query timed out for platform={platform}")
        return None
    dt_ms = (time.perf_counter() - t0) * 1000
    if dt_ms > 2000:
        log.warning("DB slow: get_platform_prompt took %.1f ms", dt_ms)
    data = res.data if res else None
    if not data or "system_prompt" not in data:
        raise ValueError(f"No system_prompt for platform={platform}")
    return data["system_prompt"]

async def get_platform_rules(platform: str) -> Dict[str, Any]:
    sb = get_client()
    t0 = time.perf_counter()
    try:
        res = await asyncio.wait_for(
            asyncio.to_thread(lambda: sb.table("platform_rules").select("platform, name, rules, instruction_template, tips, report_url, system_prompt, rules_version").eq("platform", platform).single().execute()),
            timeout=2.0
        )
    except asyncio.TimeoutError:
        log.warning(f"get_platform_rules: Supabase query timed out for platform={platform}")
        raise ValueError(f"No rules for platform={platform}")
    dt_ms = (time.perf_counter() - t0) * 1000
    if dt_ms > 2000:
        log.warning("DB slow: get_platform_rules took %.1f ms", dt_ms)
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

def log_interaction(chat_id: int, platform: str, input_text: str, output_json: dict, *, request_id: str | None = None, meta: dict | None = None):
    payload = {
        "chat_id": chat_id,
        "platform": platform,
        "input_text": input_text,
        "output_json": output_json,
        "request_id": request_id,
        "meta_json": meta or {},
    }
    try:
        res = sb.table("interactions").insert(payload).execute()
        return res
    except Exception as e:
        log.warning("log_interaction failed: %s", e)
        return None

def upsert_chat_state(chat_id: int, platform: str):
    try:
        ts = datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")
        payload = {
            "chat_id": chat_id,
            "platform": platform,
            "updated_at": ts,
        }
        res = sb.table("chat_state").upsert(
            payload,
            on_conflict="chat_id",     # ЯВНО, либо можно вообще убрать этот параметр
            returning="minimal"        # чтобы ответ был компактным
        ).execute()
        return res
    except Exception as e:
        log.exception("db.upsert_chat_state failed: %s", e)
        return None

async def set_chat_state(chat_id: int, platform: str) -> None:
    """
    Save or update chat state with selected platform
    """
    import datetime
    sb = get_client()
    try:
        _ = await asyncio.wait_for(
            asyncio.to_thread(lambda: sb.table("chat_state").upsert({
                "chat_id": chat_id,
                "platform": platform,
                "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
            }).execute()),
            timeout=3.0
        )
    except asyncio.TimeoutError:
        log.warning(f"set_chat_state: Supabase upsert timed out for chat_id={chat_id}")
        return

def get_platform_from_chat_state(chat_id: int):
    row = get_chat_state_with_updated_at(chat_id)
    if not row:
        return None
    if isinstance(row, dict):
        return row.get("platform")
    if isinstance(row, list) and row:
        item = row[0]
        return item.get("platform") if isinstance(item, dict) else None
    return None

def get_chat_state_with_updated_at(chat_id: int):
    try:
        res = sb.table("chat_state") \
            .select("platform, updated_at") \
            .eq("chat_id", chat_id) \
            .maybe_single() \
            .execute()
        if res and res.data:
            data = res.data[0] if isinstance(res.data, list) and len(res.data) > 0 else res.data
            return data
        return None
    except Exception as e:
        log.exception("db.get_chat_state_with_updated_at failed: %s", e)
        return None

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

    t0 = time.perf_counter()
    res = sb.table("interactions").select("*", count="exact") \
        .eq("chat_id", chat_id) \
        .gte("created_at", start_of_day) \
        .lte("created_at", end_of_day) \
        .execute()
    dt_ms = (time.perf_counter() - t0) * 1000
    if dt_ms > 2000:
        log.warning("DB slow: count_interactions_by_chat_id took %.1f ms", dt_ms)
    return res.count or 0

def check_rate_limit(chat_id: int, utc_day: str, threshold: int = 10) -> tuple[int, bool]:
    """
    Check rate limit for chat_id on utc_day.
    Returns (hits_before, allowed) where allowed is True if hits_before < threshold.
    Does not increment the counter.
    """
    sb = get_client()
    t0 = time.perf_counter()
    res = sb.table("rate_limits").select("hits").eq("chat_id", chat_id).eq("utc_day", utc_day).maybe_single().execute()
    dt_ms = (time.perf_counter() - t0) * 1000
    if dt_ms > 2000:
        log.warning("DB slow: check_rate_limit took %.1f ms", dt_ms)
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
    t0 = time.perf_counter()
    try:
        res = sb.rpc("increment_rate_limit", {"p_chat_id": chat_id, "p_utc_day": utc_day, "p_threshold": threshold}).execute()
        dt_ms = (time.perf_counter() - t0) * 1000
        if dt_ms > 3000:
            log.warning("DB slow: increment_rate_limit took %.1f ms", dt_ms)
        return res.data[0] if res and res.data else False
    except Exception as e:
        log.warning(f"Failed to increment rate limit: {e}")
        return False

def get_interaction_by_request_id(request_id: str) -> Optional[Dict[str, Any]]:
    """
    Get interaction by request_id for idempotency.
    Returns dict with interaction data if found, None otherwise.
    """
    sb = get_client()
    
    try:
        # Query by request_id
        res = sb.table("interactions").select("*").eq("request_id", request_id).execute()
        if res and res.data and len(res.data) > 0:
            return res.data[0]
        return None
    except Exception as e:
        log.warning(f"Failed to get interaction by request_id: {e}")
        return None

def get_cached_request_by_content(chat_id: int, text: str, platform: str) -> Optional[Dict[str, Any]]:
    """
    Get cached response by content (chat_id, text, platform) for caching repeated requests.
    Returns dict with 'response' and 'status' if found, None otherwise.
    """
    import hashlib
    sb = get_client()
    # Create hash of the text for comparison
    text_hash = hashlib.sha256(text.encode('utf-8')).hexdigest()
    
    t0 = time.perf_counter()
    try:
        # Query by chat_id, text_hash and platform
        res = sb.table("request_cache").select("response, status").eq("chat_id", chat_id).eq("text_hash", text_hash).eq("platform", platform).execute()
        dt_ms = (time.perf_counter() - t0) * 1000
        if dt_ms > 2000:
            log.warning("DB slow: get_cached_request_by_content took %.1f ms", dt_ms)
        if res and res.data and len(res.data) > 0:
            return res.data[0]
        return None
    except Exception as e:
        log.warning(f"Failed to get cached request by content: {e}")
        return None

def cache_request_by_content(chat_id: int, text: str, platform: str, response: Dict[str, Any], status: int = 200) -> None:
    """
    Cache response by content (chat_id, text, platform) for caching repeated requests.
    """
    import hashlib
    sb = get_client()
    # Create hash of the text for comparison
    text_hash = hashlib.sha256(text.encode('utf-8')).hexdigest()
    
    t0 = time.perf_counter()
    try:
        sb.table("request_cache").upsert({
            "chat_id": chat_id,
            "text_hash": text_hash,
            "platform": platform,
            "response": response,
            "status": status
        }).execute()
        dt_ms = (time.perf_counter() - t0) * 1000
        if dt_ms > 3000:
            log.warning("DB slow: cache_request_by_content took %.1f ms", dt_ms)
    except Exception as e:
        log.warning(f"Failed to cache request by content: {e}")

def cache_request_by_content(chat_id: int, text: str, platform: str, response: Dict[str, Any], status: int) -> None:
    """
    Cache response by content (chat_id, text, platform) for caching repeated requests.
    """
    import hashlib
    sb = get_client()
    # Create hash of the text for comparison
    text_hash = hashlib.sha256(text.encode('utf-8')).hexdigest()
    
    t0 = time.perf_counter()
    try:
        sb.table("request_cache").upsert({
            "chat_id": chat_id,
            "text_hash": text_hash,
            "platform": platform,
            "response": response,
            "status": status
        }).execute()
        dt_ms = (time.perf_counter() - t0) * 1000
        if dt_ms > 3000:
            log.warning("DB slow: cache_request_by_content took %.1f ms", dt_ms)
    except Exception as e:
        log.warning(f"Failed to cache request by content: {e}")

def get_cached_by_content(chat_id: int, text_hash: str, platform: str):
    try:
        q = sb.table("request_cache_content") \
              .select("result_json, created_at, expires_at") \
              .eq("chat_id", chat_id) \
              .eq("text_hash", text_hash) \
              .eq("platform", platform) \
              .maybe_single()
        res = q.execute()
        return res.data or None
    except Exception as e:
        # Фолбэк на случай 406 или «object not single»
        try:
            q2 = sb.table("request_cache_content") \
                   .select("result_json, created_at, expires_at") \
                   .eq("chat_id", chat_id) \
                   .eq("text_hash", text_hash) \
                   .eq("platform", platform) \
                   .limit(1)
            res2 = q2.execute()
            rows = res2.data or []
            return rows[0] if rows else None
        except Exception as e2:
            log.warning("get_cached_by_content fallback failed: %s", e2)
            return None

def cache_request_by_content_new(chat_id: int, text: str, platform: str, result: Dict[str, Any]) -> None:
    """
    Cache response by content (chat_id, text, platform) to correct table.
    """
    import hashlib
    import datetime as dt
    sb = get_client()
    # Create hash of the text for comparison
    text_hash = hashlib.sha256(text.encode('utf-8')).hexdigest()
    
    t0 = time.perf_counter()
    try:
        sb.table("request_cache_content").upsert({
            "chat_id": chat_id,
            "text_hash": text_hash,
            "platform": platform,
            "result_json": result,
            "created_at": dt.datetime.now(dt.timezone.utc).isoformat()
        }).execute()
        dt_ms = (time.perf_counter() - t0) * 100
        if dt_ms > 3000:
            log.warning("DB slow: cache_request_by_content_new took %.1f ms", dt_ms)
    except Exception as e:
        log.warning(f"Failed to cache request by content: {e}")

def cache_request_by_content_error(chat_id: int, text: str, platform: str, result: Dict[str, Any]) -> None:
    """
    Cache error response by content (chat_id, text, platform) to correct table.
    """
    import hashlib
    import datetime as dt
    sb = get_client()
    # Create hash of the text for comparison
    text_hash = hashlib.sha256(text.encode('utf-8')).hexdigest()
    
    t0 = time.perf_counter()
    try:
        sb.table("request_cache_content").upsert({
            "chat_id": chat_id,
            "text_hash": text_hash,
            "platform": platform,
            "result_json": result,
            "created_at": dt.datetime.now(dt.timezone.utc).isoformat()
        }).execute()
        dt_ms = (time.perf_counter() - t0) * 1000
        if dt_ms > 3000:
            log.warning("DB slow: cache_request_by_content_error took %.1f ms", dt_ms)
    except Exception as e:
        log.warning(f"Failed to cache request by content: {e}")

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