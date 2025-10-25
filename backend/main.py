from fastapi import FastAPI, HTTPException, Request
from typing import Dict, Any, Optional
import re
import asyncio
import time
import platform
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

@app.on_event("startup")
async def startup_event():
    """Preload platform rules on startup"""
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

async def compose_async(platform: str, text: str, chat_id: Optional[str] = None, business_type: Optional[str] = None) -> dict:
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
        db.log_interaction(chat_id, platform, text, result, chat_id=chat_id if chat_id else None)
    except Exception as e:
        log.warning(f"log_interaction failed: {e}")

    return result


@app.post("/compose", response_model=ComposeResponse)
async def compose_endpoint(req: ComposeRequest):
    try:
        result = await compose_async(req.platform, req.text, req.tg_user_id, req.business_type)
        return ComposeResponse(**result)
    except Exception as e:
        log.exception("compose failed")
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/state/set")
def set_state(req: StateSetRequest):
    """
    Save chat state with selected platform
    """
    try:
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
            log.warning(f"No X-Request-ID header for chat_id={req.chat_id}")
            # Continue without idempotency for backward compatibility

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

        # Check idempotency cache first
        if request_id:
            try:
                cached = db.get_cached_request(req.chat_id, utc_day, request_id)
                log.info(f"cache | hit={cached is not None} | chat_id={req.chat_id} | req_id={request_id} | utc_day={utc_day}")
                if cached:
                    # Return cached response without incrementing rate limit
                    if cached["status"] == 200:
                        return ComposeResponse(**cached["response"])
                    else:
                        raise HTTPException(status_code=cached["status"], detail=cached["response"])
            except Exception as e:
                log.warning(f"Failed to check request cache: {e}")
                # Continue without caching

        # Check rate limit (without increment)
        hits_before, allowed = db.check_rate_limit(req.chat_id, utc_day, threshold)
        decision = "ok" if allowed else "429"
        log.info(f"rate | chat_id={req.chat_id} | utc_day={utc_day} | hits_before={hits_before} | threshold={threshold} | decision={decision} | req_id={request_id or 'none'} | now_utc={now_utc.isoformat()}")

        if not allowed:
            # Cache the 429 response for idempotency
            if request_id:
                db.cache_request(req.chat_id, utc_day, request_id, {"error": "limit_reached", "reset_at": "24 hours"}, 429)
            reset_at = "soon" if dev_mode else "24 hours"
            raise HTTPException(status_code=429, detail={"error": "limit_reached", "reset_at": reset_at})

        # Call internal async compose function with retry logic for LLM rate limits
        max_retries = 2
        for attempt in range(max_retries + 1):
            try:
                result = await compose_async(platform, req.text, str(req.chat_id), business_type=None)
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
                        # Cache the LLM 429 response
                        if request_id:
                            db.cache_request(req.chat_id, utc_day, request_id, {"error": "limit_reached", "reset_at": "soon"}, 429)
                        raise HTTPException(status_code=429, detail={"error": "limit_reached", "reset_at": "soon"})
                else:
                    # Re-raise if it's not an LLM rate limit error
                    raise llm_error

        # Atomically increment rate limit after successful LLM call
        increment_success = db.increment_rate_limit(req.chat_id, utc_day, threshold)
        if not increment_success:
            log.warning(f"Failed to increment rate limit for chat_id={req.chat_id}, utc_day={utc_day}")

        # Cache successful response for idempotency
        if request_id:
            db.cache_request(req.chat_id, utc_day, request_id, result, 200)

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

        log.info(f"Extracted: platform={platform}, business_type={business_type}, tg_user_id={tg_user_id}, text_length={len(complaint_text)}")

        # Use data from payload directly
        result = await compose_async(platform, complaint_text, tg_user_id, business_type=business_type)

        log.info(f"Compose result: {result}")

        # Wrap response in 'response' key for n8n parsing
        return {"response": result.dict()}

    except HTTPException:
        raise
    except Exception as e:
        log.exception("n8n webhook processing failed")
        raise HTTPException(status_code=500, detail=f"Processing failed: {str(e)}")
