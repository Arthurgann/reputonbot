import os
import platform
import re
import time
import asyncio
from typing import Dict, Any, Optional

from fastapi import FastAPI, HTTPException, Request, Response

from .models.schemas import ComposeRequest, ComposeResponse, StateSetRequest, ComposeFromStateRequest
from . import services
from .services import db, llm
from .services.logger import log
from .services.probability import score_probability


# Use uvloop for better async performance (only on non-Windows systems)
try:
    if platform.system() != "Windows":
        import uvloop  # type: ignore
        uvloop.install()
except Exception:
    pass

app = FastAPI(title="ReputonBot Backend", version="0.2.0")

# Profiling middleware
@app.middleware("http")
async def add_timing_headers(request: Request, call_next):
    start_time = time.time()
    
    # Initialize timing values
    request.state.db_time_ms = 0
    request.state.llm_time_ms = 0
    
    response = await call_next(request)
    
    # Calculate total elapsed time
    elapsed_ms = (time.time() - start_time) * 1000
    
    # Add timing headers to response
    response.headers["X-Elapsed-ms"] = f"{elapsed_ms:.1f}"
    
    if hasattr(request.state, 'db_time_ms') and request.state.db_time_ms > 0:
        response.headers["X-DB-ms"] = f"{request.state.db_time_ms:.1f}"
    
    if hasattr(request.state, 'llm_time_ms') and request.state.llm_time_ms > 0:
        response.headers["X-LLM-ms"] = f"{request.state.llm_time_ms:.1f}"
    
    # Always add X-Request-ID - echo if present or add generated one
    request_id = request.headers.get("X-Request-ID")
    if not request_id:
        # Generate a request ID if not provided
        import uuid
        request_id = str(uuid.uuid4())
    
    response.headers["X-Request-ID"] = request_id
    
    return response

# Store start time for uptime calculation
@app.on_event("startup")
async def startup_event():
    """Preload platform rules on startup"""
    import time
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
def readyz():
    import time
    from .services.db import get_client
    from .config import settings
    
    # Get app version from environment, default to 'dev'
    version = settings.APP_VERSION if hasattr(settings, 'APP_VERSION') else os.getenv("APP_VERSION", "dev")
    
    # For now, readyz duplicates healthz
    # Future: Add additional checks (e.g., cache readiness) here
    uptime_s = time.time() - app.state.start_time
    
    # Test database connection
    ready = True
    try:
        # Check if required environment variables are present
        if not settings.SUPABASE_URL or not settings.SUPABASE_SERVICE_ROLE_KEY:
            ready = False
        else:
            sb = get_client()
            # Light ping using select from a guaranteed existing table
            sb.table("platform_rules").select('platform').limit(1).execute()
    except Exception as e:
        ready = False
    
    result = {
        "ready": ready,
        "version": version
    }
    
    if not ready:
        from fastapi.responses import JSONResponse
        return JSONResponse(content=result, status_code=503)
    
    return result

async def compose_async(platform: str, text: str, chat_id: Optional[str] = None, business_type: Optional[str] = None, request_id: Optional[str] = None) -> dict:
    """
    Internal async function to compose complaint response based on platform and text
    """
    # Remove links from text
    text = re.sub(r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+', '', text)
    text = re.sub(r'www\.(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+', '', text)
    text = text.strip()

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
        db.log_interaction(chat_id, platform, text, result, chat_id=chat_id if chat_id else None, request_id=request_id)
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
            cached = db.get_cached_request_by_content(req.tg_user_id, req.text, req.platform)
            log.info(f"compose cache | content hit={cached is not None} | chat_id={req.tg_user_id} | platform={req.platform}")
            if cached:
                # Return cached response
                if cached["status"] == 200:
                    return ComposeResponse(**cached["response"])
                else:
                    raise HTTPException(status_code=cached["status"], detail=cached["response"])
        except Exception as e:
            log.warning(f"Failed to check content cache: {e}")
            # Continue without content caching
        
        result = await compose_async(req.platform, req.text, req.tg_user_id, req.business_type, request_id=request_id)
        
        # Log the interaction with request_id for idempotency
        try:
            db.log_interaction(req.tg_user_id, req.platform, req.text, result, chat_id=req.tg_user_id, request_id=request_id)
        except Exception as e:
            log.warning(f"log_interaction failed: {e}")
        
        # Also cache by content for future requests with different request_id but same content
        try:
            db.cache_request_by_content(req.tg_user_id, req.text, req.platform, result, 200)
        except Exception as e:
            log.warning(f"Failed to cache request by content: {e}")
        
        return ComposeResponse(**result)
    except Exception as e:
        log.exception("compose failed")
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/state/set")
def set_state(req: StateSetRequest, request: Request):
    """
    Save chat state with selected platform
    """
    try:
        # Extract X-Request-ID from headers
        request_id = request.headers.get("X-Request-ID")
        if request_id:
            log.info(f"Processing state/set with X-Request-ID: {request_id} for chat_id={req.chat_id}")
        
        # Get current platform from chat state
        current_platform = db.get_platform_from_chat_state(req.chat_id)
        
        # If the platform is already set to the same value, return success without updating
        if current_platform and current_platform.strip() == req.platform.strip():
            return {"status": "ok", "chat_id": req.chat_id, "platform": req.platform}
        
        db.set_chat_state(req.chat_id, req.platform)
        return {"status": "ok", "chat_id": req.chat_id, "platform": req.platform}
    except Exception as e:
        log.exception("set_state failed")
        raise HTTPException(status_code=500, detail=str(e))

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
async def compose_from_state(req: ComposeFromStateRequest, request: Request):
    """
    Compose response based on platform stored in chat state (fully async)
    """
    start_time = time.time()
    try:
        # Extract X-Request-ID from headers
        request_id = request.headers.get("X-Request-ID")
        if not request_id:
            # Generate a request ID if not provided
            import uuid
            request_id = str(uuid.uuid4())
            log.info(f"No X-Request-ID header for chat_id={req.chat_id}, generated: {request_id}")
        else:
            log.info(f"Processing request with X-Request-ID: {request_id} for chat_id={req.chat_id}")

        # TTL check for platform selection
        TTL = dt.timedelta(hours=24)

        # Get platform and updated_at from chat state using optimized query
        row = db.get_chat_state_with_updated_at(req.chat_id)

        if not row or not row.get("platform"):
            log.info(f"compose check | chat_id={req.chat_id} | platform=None | chosen_at=None | now=None | zone=None | decision=no_platform")
            raise HTTPException(status_code=409, detail={"error": "no_platform"})

        platform = row["platform"].strip()  # Clean platform value
        updated_at_str = row.get("updated_at")

        # Ensure we have updated_at
        if not updated_at_str:
            log.info(f"compose check | chat_id={req.chat_id} | platform={platform} | chosen_at=None | now=None | zone=None | decision=no_updated_at")
            raise HTTPException(status_code=409, detail={"error": "platform_expired"})

        ts = ensure_utc(updated_at_str)
        if not ts:
            log.info(f"compose check | chat_id={req.chat_id} | platform={platform} | chosen_at={updated_at_str} | now=None | zone=None | decision=invalid_timestamp")
            raise HTTPException(status_code=409, detail={"error": "platform_expired"})

        now = dt.datetime.now(dt.timezone.utc)
        is_expired = now - ts > TTL

        # Log the decision
        decision = "expired" if is_expired else "ok"
        log.info(f"compose check | chat_id={req.chat_id} | platform={platform} | chosen_at={ts.isoformat()} | now={now.isoformat()} | zone=UTC | decision={decision}")

        if is_expired:
            raise HTTPException(status_code=409, detail={"error": "platform_expired"})

        # Rate limiting logic
        import os
        dev_mode = os.getenv("ENVIRONMENT") == "development" or os.getenv("FASTAPI_ENV") == "dev"
        threshold = 30 if dev_mode else 10

        # Calculate UTC day using (now() AT TIME ZONE 'UTC')::date format
        now_utc = dt.datetime.now(dt.timezone.utc)
        utc_day = now_utc.date().isoformat()

        # Extract X-Request-ID from headers
        request_id = request.headers.get("X-Request-ID")
        if not request_id:
            # Generate a request ID if not provided
            import uuid
            request_id = str(uuid.uuid4())
        
        # Check idempotency first: interactions.request_id
        cached_interaction = db.get_interaction_by_request_id(request_id)
        log.info(f"cache | idempotency hit={cached_interaction is not None} | chat_id={req.chat_id} | req_id={request_id}")
        if cached_interaction and cached_interaction.get("output_json"):
            # Return cached response without incrementing rate limit
            return ComposeResponse(**cached_interaction["output_json"])
        
        # Check content cache: (chat_id, text_hash, platform)
        try:
            cached = db.get_cached_request_by_content(req.chat_id, req.text, platform)
            log.info(f"cache | content hit={cached is not None} | chat_id={req.chat_id} | platform={platform}")
            if cached:
                # Return cached response without incrementing rate limit
                if cached["status"] == 200:
                    return ComposeResponse(**cached["response"])
                else:
                    raise HTTPException(status_code=cached["status"], detail=cached["response"])
        except Exception as e:
            log.warning(f"Failed to check content cache: {e}")
            # Continue without content caching

        # Check rate limit (without increment)
        hits_before, allowed = db.check_rate_limit(req.chat_id, utc_day, threshold)
        decision = "ok" if allowed else "429"
        log.info(f"rate | chat_id={req.chat_id} | utc_day={utc_day} | hits_before={hits_before} | threshold={threshold} | decision={decision} | now_utc={now_utc.isoformat()}")

        if not allowed:
            # Log the 429 response for idempotency
            try:
                db.log_interaction(str(req.chat_id), platform, req.text, {"error": "limit_reached", "reset_at": "24 hours"}, chat_id=req.chat_id, request_id=request_id)
            except Exception as e:
                log.warning(f"log_interaction failed: {e}")
            
            # Also cache the 429 response by content for consistency
            try:
                db.cache_request_by_content(req.chat_id, req.text, platform, {"error": "limit_reached", "reset_at": "24 hours"}, 429)
            except Exception as e:
                log.warning(f"Failed to cache 429 response by content: {e}")
            
            reset_at = "soon" if dev_mode else "24 hours"
            raise HTTPException(status_code=429, detail={"error": "limit_reached", "reset_at": reset_at})

        # Call internal async compose function with retry logic for LLM rate limits
        max_retries = 2
        for attempt in range(max_retries + 1):
            try:
                result = await compose_async(platform, req.text, str(req.chat_id), business_type=None, request_id=request_id)
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
                        log.info(f"LLM rate limit reached after retries for chat_id {req.chat_id}")
                        # Log the LLM 429 response for idempotency
                        try:
                            db.log_interaction(str(req.chat_id), platform, req.text, {"error": "limit_reached", "reset_at": "soon"}, chat_id=req.chat_id, request_id=request_id)
                        except Exception as e:
                            log.warning(f"log_interaction failed: {e}")
                        
                        # Also cache the LLM 429 response by content for consistency
                        try:
                            db.cache_request_by_content(req.chat_id, req.text, platform, {"error": "limit_reached", "reset_at": "soon"}, 429)
                        except Exception as e:
                            log.warning(f"Failed to cache LLM 429 response by content: {e}")
                        
                        raise HTTPException(status_code=429, detail={"error": "limit_reached", "reset_at": "soon"})
                else:
                    # Re-raise if it's not an LLM rate limit error
                    raise llm_error

        # Atomically increment rate limit after successful LLM call
        increment_success = db.increment_rate_limit(req.chat_id, utc_day, threshold)
        if not increment_success:
            log.warning(f"Failed to increment rate limit for chat_id={req.chat_id}, utc_day={utc_day}")

        # Log the interaction with request_id for idempotency
        try:
            db.log_interaction(str(req.chat_id), platform, req.text, result, chat_id=req.chat_id, request_id=request_id)
        except Exception as e:
            log.warning(f"log_interaction failed: {e}")
        
        # Also cache by content for future requests with different request_id but same content
        try:
            db.cache_request_by_content(req.chat_id, req.text, platform, result, 200)
        except Exception as e:
            log.warning(f"Failed to cache request by content: {e}")

        # Log total response time
        total_time = time.time() - start_time
        log.info(f"compose_from_state completed | chat_id={req.chat_id} | total_time={total_time:.2f}s")

        return ComposeResponse(**result)
    except HTTPException:
        raise
    except Exception as e:
        log.exception("compose_from_state failed")
        raise HTTPException(status_code=500, detail=str(e))

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
            cached = db.get_cached_request_by_content(tg_user_id, complaint_text, platform)
            log.info(f"n8n cache | content hit={cached is not None} | chat_id={tg_user_id} | platform={platform}")
            if cached:
                # Return cached response
                if cached["status"] == 200:
                    return {"response": cached["response"]}
                else:
                    raise HTTPException(status_code=cached["status"], detail=cached["response"])
        except Exception as e:
            log.warning(f"Failed to check content cache: {e}")
            # Continue without content caching

        # Use data from payload directly
        result = await compose_async(platform, complaint_text, tg_user_id, business_type=business_type, request_id=request_id)
        
        # Log the interaction with request_id for idempotency
        try:
            db.log_interaction(tg_user_id, platform, complaint_text, result, chat_id=tg_user_id, request_id=request_id)
        except Exception as e:
            log.warning(f"log_interaction failed: {e}")
        
        # Cache successful response by content
        try:
            db.cache_request_by_content(tg_user_id, complaint_text, platform, result, 200)
        except Exception as e:
            log.warning(f"Failed to cache request by content: {e}")

        log.info(f"Compose result: {result}")

        # Wrap response in 'response' key for n8n parsing
        return {"response": result.dict()}

    except HTTPException:
        raise
    except Exception as e:
        log.exception("n8n webhook processing failed")
        raise HTTPException(status_code=500, detail=f"Processing failed: {str(e)}")
