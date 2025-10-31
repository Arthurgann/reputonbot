import os
import platform
import re
import time
import asyncio
import inspect
from typing import Dict, Any, Optional

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from .models.schemas import ComposeRequest, ComposeResponse, StateSetRequest
from . import services
from .services import db, llm
from hashlib import sha256
from .services.logger import log
from .services.probability import score_probability
from backend.services.db import get_client
def clean_str(v):
    return v.strip() if isinstance(v, str) else ""


# Use uvloop for better async performance (only on non-Windows systems)
try:
    if platform.system() != "Windows":
        import uvloop  # type: ignore
        uvloop.install()
except Exception:
    pass

app = FastAPI(title="ReputonBot Backend", version="0.2.0")

# Profiling middleware
import time
from time import perf_counter

@app.middleware("http")
async def add_timing_headers(request: Request, call_next):
    # Add ERROR log at the very top of middleware
    log.error("mw: got %s %s", request.method, request.url.path)
    
    # Diagnostic shortcut - check for x-cfs-echo header before call_next
    if request.headers.get("x-cfs-echo") == "1" and request.url.path == "/compose_from_state":
        # Set the same headers that middleware normally sets
        resp = JSONResponse({"ok": True, "stage": "middleware"}, status_code=200)
        import uuid
        request_id = request.headers.get("X-Request-ID")
        if not request_id:
            request_id = str(uuid.uuid4())
        resp.headers["X-Request-ID"] = request_id
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers["X-Elapsed-ms"] = "0.0"
        resp.headers["X-DB-ms"] = "0.0"
        resp.headers["X-LLM-ms"] = "0.0"
        return resp
    
    # Read/generate request_id and put in request.state.request_id
    request_id = request.headers.get("X-Request-ID")
    if not request_id:
        import uuid
        request_id = str(uuid.uuid4())
    request.state.request_id = request_id
    
    # Initialize timing values
    request.state.db_ms = 0.0
    request.state.llm_ms = 0.0
    t0 = perf_counter()
    
    try:
        response = await asyncio.wait_for(call_next(request), timeout=30.0)
        # Add security headers to response
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
    except asyncio.TimeoutError:
        response = JSONResponse(status_code=503, content={"error": "busy", "message": "service timeout"})
        # Add security headers to response
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
    
    # Add timing headers to response
    response.headers["X-Request-ID"] = request.state.request_id
    response.headers["X-Elapsed-ms"] = f"{(perf_counter()-t0)*1000:.1f}"
    response.headers["X-DB-ms"] = f"{getattr(request.state,'db_ms',0.0):.1f}"
    response.headers["X-LLM-ms"] = f"{getattr(request.state,'llm_ms',0.0):.1f}"
    
    return response

# Store start time for uptime calculation
@app.on_event("startup")
async def startup_event():
    """Preload platform rules on startup"""
    import time
    from .config import settings, get_log_level
    from .services.logger import log
    import logging
    
    # Configure logging level based on environment
    root_logger = logging.getLogger()
    root_logger.setLevel(get_log_level())
    log.setLevel(get_log_level())
    
    # Log the environment and logging level at startup
    log.info(f"Starting application in {settings.APP_ENV} environment with log level {logging.getLevelName(get_log_level())}")
    
    app.state.start_time = time.time()
    await db.preload_platform_rules()
    # Start background task to refresh cache every 5 minutes
    asyncio.create_task(refresh_cache_periodically())

async def refresh_cache_periodically():
    """Refresh platform rules cache every 5 minutes"""
    while True:
        await asyncio.sleep(300)  # 5 minutes
        try:
            await db.refresh_platform_rules_cache()
        except Exception as e:
            log.warning(f"Failed to refresh platform rules cache: {e}")

@app.get("/health")
def health():
    return {"ok": True}

@app.get("/healthz")
def healthz():
    import time
    from .services.db import get_client
    from .config import settings
    
    # Get app version from environment, default to 'dev'
    version = settings.APP_VERSION if hasattr(settings, 'APP_VERSION') else os.getenv("APP_VERSION", "dev")
    uptime_s = time.time() - app.state.start_time
    
    # Test database connection
    db_status = "ok"
    status = "ok"
    http_status = 200
    reason = None
    
    try:
        # Check if required environment variables are present
        if not settings.SUPABASE_URL or not settings.SUPABASE_SERVICE_ROLE_KEY:
            db_status = "down"
            status = "down"
            http_status = 503
            reason = "env_missing"
        else:
            sb = get_client()
            # Light ping using select from a guaranteed existing table
            sb.table("platform_rules").select('platform').limit(1).execute()
    except Exception as e:
        db_status = "down"
        status = "down"
        http_status = 503
        # Determine specific error type
        error_msg = str(e).lower()
        if "401" in error_msg or "403" in error_msg or "auth" in error_msg:
            reason = "auth_error"
        elif "timeout" in error_msg:
            reason = "timeout"
        elif "connection" in error_msg or "network" in error_msg:
            reason = "network_error"
        else:
            reason = "unknown_error"
    
    result = {
        "status": status,
        "version": version,
        "uptime_s": int(uptime_s),
        "db": db_status
    }
    
    if reason:
        result["reason"] = reason
    
    if http_status == 503:
        from fastapi.responses import JSONResponse
        return JSONResponse(content=result, status_code=http_status)
    
    return result

@app.get("/readyz")
async def readyz():
    """
    Readiness probe: проверяет доступность БД и наличие хотя бы одной записи в platform_rules.
    200 {"ready": true} если всё ок; иначе 503 {"ready": false}.
    """
    try:
        sb = get_client()
        res = sb.table("platform_rules").select("platform").limit(1).execute()
        if not res or not getattr(res, "data", None):
            return JSONResponse(status_code=503, content={"ready": False})
        return {"ready": True}
    except Exception as e:
        log.warning(f"/readyz failed: {e}")
        return JSONResponse(status_code=503, content={"ready": False})

async def compose_async(platform: str, text: str, chat_id: Optional[str] = None, business_type: Optional[str] = None, request_id: Optional[str] = None) -> dict:
    """
    Internal async function to compose complaint response based on platform and text
    """
    # Remove links from text
    text = re.sub(r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+', '', text)
    text = re.sub(r'www\.(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+', '', text)
    text = clean_str(text)

    # Get platform rules from cache (fast)
    platform_data = db.get_platform_rules_cached(platform)

    # Extract all required fields from platform data
    system_prompt = platform_data["system_prompt"]
    rules = platform_data["rules"] or {}
    instruction_template = platform_data["instruction_template"]
    tips = platform_data["tips"]
    report_url = platform_data["report_url"]
    rules_version = platform_data["rules_version"]

    # Calculate probability using heuristic function
    probability_label = score_probability(text, rules)

    # Call LLM asynchronously with all required parameters
    result = await llm.compose_text_async(
        system_prompt,
        text,
        business_type,
        platform,
        rules,
        instruction_template,
        tips,
        report_url
    )

    # Ensure probability_label is set if not provided by LLM
    if "probability_label" not in result or result["probability_label"] is None:
        result["probability_label"] = probability_label

    # Add additional fields from platform data
    result["rules_version"] = rules_version
    result["report_url"] = report_url
    result["system_prompt"] = system_prompt
    result["rules"] = rules
    result["instruction_template"] = instruction_template

    # Log the interaction (moved after LLM call for performance)
    try:
        db.log_interaction(chat_id, platform, text, result, request_id=request_id)
    except Exception as e:
        log.warning(f"log_interaction failed: {e}")

    return result


@app.post("/compose", response_model=ComposeResponse)
async def compose_endpoint(req: ComposeRequest, request: Request):
    try:
        # Extract X-Request-ID from headers
        request_id = request.headers.get("X-Request-ID")
        if not request_id:
            # Generate a request ID if not provided
            import uuid
            request_id = str(uuid.uuid4())
        
        # Check idempotency first: interactions.request_id
        cached_interaction = db.get_interaction_by_request_id(request_id)
        log.info(f"compose cache | idempotency hit={cached_interaction is not None} | chat_id={req.tg_user_id} | req_id={request_id}")
        if cached_interaction and cached_interaction.get("output_json"):
            # Return cached response
            return ComposeResponse(**cached_interaction["output_json"])
        
        # Check content cache: (chat_id, text_hash, platform)
        try:
            import hashlib
            text_sha = hashlib.sha256(req.text.encode('utf-8')).hexdigest()
            hit, payload = False, None
            if CONTENT_CACHE_ENABLED:
                row = db.get_cached_by_content(req.tg_user_id, text_sha, req.platform)
                hit = bool(row)
                payload = row["result_json"] if row else None
            else:
                hit, payload = False, None
            log.info(f"compose cache | content hit={hit} | chat_id={req.tg_user_id} | platform={req.platform}")
            if hit and payload:
                # Return cached response
                return ComposeResponse(**payload)
            # If we have a row but no result_json, continue without cache
        except Exception as e:
            log.warning(f"Failed to check content cache: {e}")
            # Continue without content caching
        
        result = await compose_async(req.platform, req.text, req.tg_user_id, req.business_type, request_id=request_id)
        
        # Log the interaction with request_id for idempotency
        try:
            db.log_interaction(req.tg_user_id, req.platform, req.text, result, request_id=request_id)
        except Exception as e:
            log.warning(f"log_interaction failed: {e}")

        # Also cache by content for future requests with different request_id but same content
        if CONTENT_CACHE_ENABLED:
            try:
                db.cache_request_by_content_new(req.tg_user_id, text_hash, req.platform, result, ttl_seconds=3600)
            except Exception as e:
                log.warning(f"Failed to cache request by content: {e}")
        
        return ComposeResponse(**result)
    except Exception as e:
        text_len = len(req.text) if hasattr(req, 'text') else 0
        text_sha = sha256(req.text.encode()).hexdigest()[:12] if hasattr(req, 'text') else ""
        log.exception(f"compose failed | text_len={text_len} | text_sha={text_sha} | platform={req.platform} | chat_id={req.tg_user_id}")
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/state/set")
async def state_set(request: Request):
    # Read request body
    data = await request.json()
    
    # Safely extract fields
    chat_id_raw = data.get("chat_id")
    try:
        chat_id = int(chat_id_raw)
    except Exception:
        chat_id = 0
    platform = clean_str(data.get("platform"))
    username = clean_str(data.get("username"))
    
    # Validation
    if not platform:
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=400,
            content={"error": "invalid_input", "field": "platform"},
        )
    
    if chat_id <= 0:
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=400,
            content={"error": "invalid_input", "field": "chat_id"},
        )
    
    # дальше текущая логика upsert/select и ответ {"status":"ok","chat_id":..., "platform":...}
    
    try:
        # Extract X-Request-ID from headers
        request_id = request.headers.get("X-Request-ID")
        if request_id:
            log.info(f"Processing state/set with X-Request-ID: {request_id} for chat_id={chat_id}")
        
        # Get current platform from chat state
        platform_db = db.get_platform_from_chat_state(chat_id)
        if not platform:
            platform = clean_str(platform_db)
        
        # If the platform is already set to the same value, return success without updating
        if platform_db and clean_str(platform_db) == platform:
            return {"status": "ok", "chat_id": chat_id, "platform": platform}
        
        res = db.upsert_chat_state(chat_id, platform)
        log.error("state_set: upsert type=%s data=%r",
                  type(res).__name__ if res else None,
                  getattr(res, "data", None))
        return {"status": "ok", "chat_id": chat_id, "platform": platform}
    except HTTPException:
        raise
    except Exception as e:
        log.exception("state_set failed: type(platform)=%s type(username)=%s", type(platform).__name__, type(username).__name__)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/__debug/chat_state")
async def __debug_chat_state(chat_id: int):
    from backend.services import db
    row = db.get_chat_state_with_updated_at(chat_id)
    return {"row": row}

import datetime as dt

def ensure_utc(dtval):
    """
    Принимает либо datetime (naive/aware), либо str (ISO, возможно с 'Z'),
    и возвращает timezone-aware datetime в UTC.
    """
    from .services.logger import log
    if isinstance(dtval, str):
        # Заменить 'Z' на '+00:00' и распарсить
        try:
            dtval = dtval.replace('Z', '+00:00')
            dtval = dt.datetime.fromisoformat(dtval)
        except ValueError:
            log.warning(f"Invalid datetime format: {dtval}")
            return None
    if isinstance(dtval, dt.datetime):
        if dtval.tzinfo is None:
            # naive datetime, добавить tzinfo=timezone.utc
            return dtval.replace(tzinfo=dt.timezone.utc)
        else:
            # aware datetime, привести к UTC
            return dtval.astimezone(dt.timezone.utc)
    log.warning(f"Invalid datetime type: {type(dtval)}, value: {dtval}")
    return None

@app.post("/compose_from_state", response_model=ComposeResponse)
async def compose_from_state(request: Request):
    """
    Compose response based on platform stored in chat state (fully async)
    """
    import os
    CONTENT_CACHE_ENABLED = os.getenv("CONTENT_CACHE_ENABLED", "1") == "1"
    
    start_time = time.time()
    log.error("cfs: ENTER")
    
    # Diagnostic handler shortcut - after first log and validations, before any await
    try:
        # Parse request body for validation
        try:
            data = await request.json()
        except Exception as e:
            log.exception("cfs: json parse failed: %s", e)
            raise HTTPException(status_code=400, detail={"error":"invalid_json"})
        
        # Extract fields safely for validation
        chat_id_raw = data.get("chat_id")
        try:
            chat_id = int(chat_id_raw)
        except Exception:
            chat_id = 0
        text = clean_str(data.get("text"))
        
        # Validation before any other logic
        if chat_id <= 0:
            raise HTTPException(400, {"error":"invalid_input","field":"chat_id"})
        
        if text == "":
            log.warning("invalid_input compose_from_state: text_len=%d text_sha=%s platform=%s chat_id=%s",
                        0, sha256(b"").hexdigest()[:12], None, chat_id)
            raise HTTPException(400, {"error":"invalid_input","field":"text","reason":"empty"})
        
        if len(text) > 10000:
            log.warning("invalid_input compose_from_state: text_len=%d text_sha=%s platform=%s chat_id=%s",
                        len(text), sha256(text.encode()).hexdigest()[:12], None, chat_id)
            raise HTTPException(400, {"error":"invalid_input","field":"text","reason":"too_long"})
        
        # Handler diagnostic return - after validation but before any await
        if request.headers.get("x-cfs-echo") == "1":
            from fastapi.responses import JSONResponse
            return JSONResponse({"ok": True, "stage": "handler-pre-parse"}, status_code=200)
    
    except HTTPException:
        raise
    except Exception:
        # If there's an error during validation, let the main try/catch handle it
        pass
    
    try:
        # Extract X-Request-ID from headers
        request_id = request.headers.get("X-Request-ID")
        if not request_id:
            # Generate a request ID if not provided
            import uuid
            request_id = str(uuid.uuid4())
        # Store request_id in request.state for middleware-echo
        request.state.request_id = request_id

        # Add log before JSON parsing
        log.error("cfs: BEFORE JSON")
        
        # Parse request body
        try:
            data = await request.json()
        except Exception as e:
            log.exception("cfs: json parse failed: %s", e)
            raise HTTPException(status_code=400, detail={"error":"invalid_json"})
        
        # Add log after JSON parsing
        log.error("cfs: AFTER JSON type=%s keys=%s", type(data).__name__, list(data.keys()) if isinstance(data, dict) else None)
        
        # Extract fields safely
        chat_id_raw = data.get("chat_id")
        try:
            chat_id = int(chat_id_raw)
        except Exception:
            chat_id = 0
        text = clean_str(data.get("text"))
        
        log.info("cfs: parsed chat_id=%s text_len=%d", chat_id, len(text))
        
        # Validation before any other logic
        if chat_id <= 0:
            raise HTTPException(400, {"error":"invalid_input","field":"chat_id"})
        
        if text == "":
            log.warning("invalid_input compose_from_state: text_len=%d text_sha=%s platform=%s chat_id=%s",
                        0, sha256(b"").hexdigest()[:12], None, chat_id)
            raise HTTPException(400, {"error":"invalid_input","field":"text","reason":"empty"})
        
        if len(text) > 10000:
            log.warning("invalid_input compose_from_state: text_len=%d text_sha=%s platform=%s chat_id=%s",
                        len(text), sha256(text.encode()).hexdigest()[:12], None, chat_id)
            raise HTTPException(400, {"error":"invalid_input","field":"text","reason":"too_long"})

        # Get platform from state
        log.error("cfs: BEFORE AWAIT get_platform chat_id=%s", chat_id)
        platform_db = db.get_platform_from_chat_state(chat_id)   # Синхронный вызов
        log.error("cfs: AFTER AWAIT get_platform type=%s value=%r", type(platform_db).__name__, platform_db)
        
        # диагностический лог типов
        log.error("cfs: types before guard: platform_db=%s", type(platform_db).__name__)

        # дефенсив-гард на случай, если всё ещё пришла корутина
        if inspect.iscoroutine(platform_db):
            log.error("cfs: platform_db is coroutine — awaiting it (defensive)")
            platform_db = await platform_db

        # и сразу после — ещё один лог
        log.error("cfs: types after guard: platform_db=%s", type(platform_db).__name__)

        platform_safe = clean_str(platform_db)

        # TTL check for platform selection
        TTL = dt.timedelta(hours=24)

        # Add log before database query
        log.error("cfs: BEFORE AWAIT get_chat_state_with_updated_at chat_id=%s", chat_id)
        # Get platform and updated_at from chat state using optimized query
        row = db.get_chat_state_with_updated_at(chat_id)
        log.error("cfs: AFTER AWAIT get_chat_state_with_updated_at row=%s", row)
        
        # диагностический лог типов для row
        log.error("cfs: types before guard: row=%s", type(row).__name__)

        # дефенсив-гард на случай, если всё ещё пришла корутина
        if inspect.iscoroutine(row):
            log.error("cfs: row is coroutine — awaiting it (defensive)")
            row = await row

        # и сразу после — ещё один лог
        log.error("cfs: types after guard: row=%s", type(row).__name__)

        if not row or not row.get("platform"):
            log.info(f"compose check | chat_id={chat_id} | platform=None | chosen_at=None | now=None | zone=None | decision=no_platform")
            raise HTTPException(status_code=409, detail={"error": "no_platform"})

        platform = clean_str(row["platform"])  # Clean platform value
        updated_at_str = row.get("updated_at")

        # Ensure we have updated_at
        if not updated_at_str:
            log.info(f"compose check | chat_id={chat_id} | platform={platform} | chosen_at=None | now=None | zone=None | decision=no_updated_at")
            raise HTTPException(status_code=409, detail={"error": "platform_expired"})

        ts = ensure_utc(updated_at_str)
        if not ts:
            log.info(f"compose check | chat_id={chat_id} | platform={platform} | chosen_at={updated_at_str} | now=None | zone=None | decision=invalid_timestamp")
            raise HTTPException(status_code=409, detail={"error": "platform_expired"})

        now = dt.datetime.now(dt.timezone.utc)
        is_expired = now - ts > TTL

        # Log the decision
        decision = "expired" if is_expired else "ok"
        log.info(f"compose check | chat_id={chat_id} | platform={platform} | chosen_at={ts.isoformat()} | now={now.isoformat()} | zone=UTC | decision={decision}")

        if is_expired:
            raise HTTPException(status_code=409, detail={"error": "platform_expired"})

        # Rate limiting logic
        dev_mode = os.getenv("ENVIRONMENT") == "development" or os.getenv("FASTAPI_ENV") == "dev"
        threshold = 30 if dev_mode else 10

        # Calculate UTC day using (now() AT TIME ZONE 'UTC')::date format
        now_utc = dt.datetime.now(dt.timezone.utc)
        utc_day = now_utc.date().isoformat()

        
        # Add log before idempotency check
        log.error("cfs: BEFORE AWAIT check_idempotency chat_id=%s", chat_id)
        # Check idempotency first: interactions.request_id
        cached_interaction = db.get_interaction_by_request_id(request_id)
        log.info(f"cache | idempotency hit={cached_interaction is not None} | chat_id={chat_id} | req_id={request_id}")
        if cached_interaction and cached_interaction.get("output_json"):
            # Return cached response without incrementing rate limit
            return ComposeResponse(**cached_interaction["output_json"])
        
        # Add log before content cache check
        log.error("cfs: BEFORE AWAIT check_content_cache chat_id=%s", chat_id)
        # Check content cache: (chat_id, text_hash, platform)
        try:
            import hashlib
            text_sha = hashlib.sha256(text.encode('utf-8')).hexdigest()
            hit, payload = False, None
            if CONTENT_CACHE_ENABLED:
                row = db.get_cached_by_content(chat_id, text_sha, platform)
                hit = bool(row)
                payload = row["result_json"] if row else None
            else:
                hit, payload = False, None
            log.info(f"cache | content hit={hit} | chat_id={chat_id} | platform={platform}")
            if hit and payload:
                # Return cached response without incrementing rate limit
                return ComposeResponse(**payload)
            # If we have a row but no result_json, continue without cache
        except Exception as e:
            log.warning(f"Failed to check content cache: {e}")
            # Continue without content caching
        log.error("cfs: AFTER AWAIT check_content_cache chat_id=%s", chat_id)

        # Check rate limit (without increment)
        hits_before, allowed = db.check_rate_limit(chat_id, utc_day, threshold)
        decision = "ok" if allowed else "429"
        log.info(f"rate | chat_id={chat_id} | utc_day={utc_day} | hits_before={hits_before} | threshold={threshold} | decision={decision} | now_utc={now_utc.isoformat()}")

        if not allowed:
            # Log the 429 response for idempotency
            try:
                db.log_interaction(chat_id, platform, text, {"error": "limit_reached", "reset_at": "24 hours"}, request_id=request_id)
            except Exception as e:
                log.warning(f"log_interaction failed: {e}")

            # Also cache the 429 response by content for consistency
            if CONTENT_CACHE_ENABLED:
                try:
                    db.cache_request_by_content_error(chat_id, text_sha, platform, {"error": "limit_reached", "reset_at": "24 hours"}, ttl_seconds=300)
                except Exception as e:
                    log.warning(f"Failed to cache 429 response by content: {e}")
            
            reset_at = "soon" if dev_mode else "24 hours"
            raise HTTPException(status_code=429, detail={"error": "limit_reached", "reset_at": reset_at})

        # Add log before calling compose_async
        log.error("cfs: BEFORE AWAIT compose_async chat_id=%s", chat_id)
        # Call internal async compose function with retry logic for LLM rate limits
        max_retries = 2
        for attempt in range(max_retries + 1):
            try:
                result = await compose_async(platform, text, str(chat_id), business_type=None, request_id=request_id)
                break
            except Exception as llm_error:
                # Check if this is an LLM rate limit error (status code 429)
                if hasattr(llm_error, 'status_code') and llm_error.status_code == 429:
                    if attempt < max_retries:
                        wait_time = (attempt + 1)  # 1s, then 2s
                        log.info(f"LLM rate limit hit, retrying in {wait_time}s (attempt {attempt + 1}/{max_retries})")
                        await asyncio.sleep(wait_time)
                        continue
                    else:
                        # After all retries, return a 429 with appropriate message
                        log.info(f"LLM rate limit reached after retries for chat_id {chat_id}")
                        # Log the LLM 429 response for idempotency
                        try:
                            db.log_interaction(chat_id, platform, text, {"error": "limit_reached", "reset_at": "soon"}, request_id=request_id)
                        except Exception as e:
                            log.warning(f"log_interaction failed: {e}")

                        # Also cache the LLM 429 response by content for consistency
                        if CONTENT_CACHE_ENABLED:
                            try:
                                db.cache_request_by_content_error(chat_id, text_sha, platform, {"error": "limit_reached", "reset_at": "soon"}, ttl_seconds=300)
                            except Exception as e:
                                log.warning(f"Failed to cache LLM 429 response by content: {e}")
                        
                        raise HTTPException(status_code=429, detail={"error": "limit_reached", "reset_at": "soon"})
                else:
                    # Re-raise if it's not an LLM rate limit error
                    raise llm_error
        log.error("cfs: AFTER AWAIT compose_async chat_id=%s", chat_id)

        # Atomically increment rate limit after successful LLM call
        increment_success = db.increment_rate_limit(chat_id, utc_day, threshold)
        if not increment_success:
            log.warning(f"Failed to increment rate limit for chat_id={chat_id}, utc_day={utc_day}")

        # Log the interaction with request_id for idempotency
        try:
            db.log_interaction(chat_id, platform, text, result, request_id=request_id)
        except Exception as e:
            log.warning(f"log_interaction failed: {e}")

        # Also cache by content for future requests with different request_id but same content
        if CONTENT_CACHE_ENABLED:
            try:
                db.cache_request_by_content_new(chat_id, text_sha, platform, result, ttl_seconds=3600)
            except Exception as e:
                log.warning(f"Failed to cache request by content: {e}")

        # Log total response time
        total_time = time.time() - start_time
        log.info(f"compose_from_state completed | chat_id={chat_id} | total_time={total_time:.2f}s")

        return ComposeResponse(**result)
    except HTTPException:
        raise
    except Exception as e:
        log.error("cfs: TOP-LEVEL FAIL")
        log.exception("cfs: unhandled error")
        if request.headers.get("x-cfs-diag") == "1":
            from fastapi.responses import JSONResponse
            return JSONResponse({"error":"server_error","msg": str(e)}, status_code=500)
        raise HTTPException(500, {"error":"server_error"})

@app.post("/webhook/n8n")
async def n8n_webhook(request: Request):
    """
    Webhook endpoint for n8n to send complaint text and receive processed response
    Proxies to /compose endpoint for consistent processing
    """
    try:
        payload = await request.json()
        log.info(f"Received n8n payload: {payload}")

        # Extract complaint text from n8n payload - this might vary depending on your n8n setup
        complaint_text = payload.get('text') or payload.get('complaint') or payload.get('message')

        if not complaint_text:
            raise HTTPException(status_code=400, detail="Missing complaint text in payload")

        # Extract platform if provided, default to a generic one
        platform = payload.get('platform', 'generic')
        business_type = payload.get('business_type')
        tg_user_id = payload.get('tg_user_id')  # Optional, for logging
        request_id = request.headers.get("X-Request-ID")  # Extract X-Request-ID from headers
        
        # If no request_id provided, generate one
        if not request_id:
            import uuid
            request_id = str(uuid.uuid4())

        log.info(f"Extracted: platform={platform}, business_type={business_type}, tg_user_id={tg_user_id}, text_length={len(complaint_text)}")

        # Check idempotency first: interactions.request_id
        cached_interaction = db.get_interaction_by_request_id(request_id)
        log.info(f"n8n cache | idempotency hit={cached_interaction is not None} | chat_id={tg_user_id} | req_id={request_id}")
        if cached_interaction and cached_interaction.get("output_json"):
            # Return cached response
            return {"response": cached_interaction["output_json"]}

        # Check content cache: (chat_id, text_hash, platform)
        try:
            import hashlib
            text_sha = hashlib.sha256(complaint_text.encode('utf-8')).hexdigest()
            hit, payload = False, None
            if CONTENT_CACHE_ENABLED:
                row = db.get_cached_by_content(tg_user_id, text_sha, platform)
                hit = bool(row)
                payload = row["result_json"] if row else None
            else:
                hit, payload = False, None
            log.info(f"n8n cache | content hit={hit} | chat_id={tg_user_id} | platform={platform}")
            if hit and payload:
                # Return cached response
                return {"response": payload}
            # If we have a row but no result_json, continue without cache
        except Exception as e:
            log.warning(f"Failed to check content cache: {e}")
            # Continue without content caching

        # Use data from payload directly
        result = await compose_async(platform, complaint_text, tg_user_id, business_type=business_type, request_id=request_id)
        # Log the interaction with request_id for idempotency
        try:
            db.log_interaction(tg_user_id, platform, complaint_text, result, request_id=request_id)
        except Exception as e:
            log.warning(f"log_interaction failed: {e}")

        
        # Cache successful response by content
        if CONTENT_CACHE_ENABLED:
            try:
                db.cache_request_by_content_new(tg_user_id, text_sha, platform, result, ttl_seconds=3600)
            except Exception as e:
                log.warning(f"Failed to cache request by content: {e}")

        log.info(f"Compose result: {result}")

        # Wrap response in 'response' key for n8n parsing
        return {"response": result.dict()}

    except HTTPException:
        raise
    except Exception as e:
        text_len = len(complaint_text) if 'complaint_text' in locals() else 0
        text_sha = sha256(complaint_text.encode()).hexdigest()[:12] if 'complaint_text' in locals() else ""
        platform_val = locals().get('platform', '')
        chat_id_val = locals().get('tg_user_id', '')
        log.exception(f"n8n webhook processing failed | text_len={text_len} | text_sha={text_sha} | platform={platform_val} | chat_id={chat_id_val}")
        raise HTTPException(status_code=500, detail=f"Processing failed: {str(e)}")
