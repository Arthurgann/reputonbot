from fastapi import FastAPI, HTTPException, Request
from typing import Dict, Any, Optional
from .models.schemas import ComposeIn, ComposeOut
from .services import db, llm
from .services.logger import logger

app = FastAPI(title="ReputonBot Backend", version="0.2.0")

@app.get("/health")
def health():
    return {"ok": True}

@app.post("/compose", response_model=ComposeOut)
def compose(req: ComposeIn):
    try:
        platform_data = db.get_platform_rules(req.platform)
        system_prompt = platform_data["system_prompt"]
        rules = platform_data.get("rules", {})
        rules_text = "\n".join([f"- {k}: {v}" for k, v in rules.items()]) if rules else "Правила не указаны"
        report_url = platform_data.get("report_url", "")

        result = llm.compose_text(system_prompt, req.text, req.business_type, req.platform, rules_text, report_url)
        # логируем, ошибки логирования не должны ронять ответ пользователю
        try:
            db.log_interaction(req.tg_user_id, req.platform, req.text, result)
        except Exception as e:
            logger.warning(f"log_interaction failed: {e}")
        return ComposeOut(**result)
    except Exception as e:
        logger.exception("compose failed")
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/webhook/n8n")
async def n8n_webhook(request: Request):
    """
    Webhook endpoint for n8n to send complaint text and receive processed response
    Proxies to /compose endpoint for consistent processing
    """
    try:
        payload = await request.json()
        logger.info(f"Received n8n payload: {payload}")

        # Extract complaint text from n8n payload - this might vary depending on your n8n setup
        complaint_text = payload.get('text') or payload.get('complaint') or payload.get('message')

        if not complaint_text:
            raise HTTPException(status_code=400, detail="Missing complaint text in payload")

        # Extract platform if provided, default to a generic one
        platform = payload.get('platform', 'generic')
        business_type = payload.get('business_type')
        tg_user_id = payload.get('tg_user_id')  # Optional, for logging

        logger.info(f"Extracted: platform={platform}, business_type={business_type}, tg_user_id={tg_user_id}, text_length={len(complaint_text)}")

        # Create ComposeIn object and call compose function
        compose_req = ComposeIn(platform=platform, text=complaint_text, business_type=business_type, tg_user_id=tg_user_id)
        result = compose(compose_req)

        logger.info(f"Compose result: {result}")

        # Wrap response in 'response' key for n8n parsing
        return {"response": result.dict()}

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("n8n webhook processing failed")
        raise HTTPException(status_code=500, detail=f"Processing failed: {str(e)}")
@app.post("/webhook/n8n")
async def n8n_webhook(request: Request):
    """
    Webhook endpoint for n8n to send complaint text and receive processed response
    Expects JSON with at least a 'text' field containing the complaint
    """
    try:
        payload = await request.json()
        
        # Extract complaint text from n8n payload - this might vary depending on your n8n setup
        complaint_text = payload.get('text') or payload.get('complaint') or payload.get('message')
        
        if not complaint_text:
            raise HTTPException(status_code=400, detail="Missing complaint text in payload")
        
        # Extract platform if provided, default to a generic one
        platform = payload.get('platform', 'generic')
        business_type = payload.get('business_type')
        tg_user_id = payload.get('tg_user_id')  # Optional, for logging
        
        # Get platform-specific prompt from Supabase
        system_prompt = db.get_platform_prompt(platform)
        
        # Process with LLM
        result = llm.compose_text(system_prompt, complaint_text, business_type)
        
        # Log the interaction
        try:
            db.log_interaction(tg_user_id, platform, complaint_text, result)
        except Exception as e:
            logger.warning(f"log_interaction failed: {e}")
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("n8n webhook processing failed")
        raise HTTPException(status_code=500, detail=f"Processing failed: {str(e)}")
