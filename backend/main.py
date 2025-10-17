from fastapi import FastAPI, HTTPException, Request
from typing import Dict, Any, Optional
from .models.schemas import ComposeRequest, ComposeResponse
from .services import db, llm
from .services.logger import logger
from .services.probability import score_probability

app = FastAPI(title="ReputonBot Backend", version="0.2.0")

@app.get("/health")
def health():
    return {"ok": True}

@app.post("/compose", response_model=ComposeResponse)
def compose(req: ComposeRequest):
    try:
        # Get platform rules from database
        platform_data = db.get_platform_rules(req.platform)
        
        # Extract all required fields from platform data
        system_prompt = platform_data["system_prompt"]
        rules = platform_data["rules"] or {}
        instruction_template = platform_data["instruction_template"]
        tips = platform_data["tips"]
        report_url = platform_data["report_url"]
        rules_version = platform_data["rules_version"]

        # Calculate probability using heuristic function
        probability_label = score_probability(req.text, rules)

        # Call LLM with all required parameters
        result = llm.compose_text(
            system_prompt,
            req.text,
            req.business_type,
            req.platform,
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
        
        # Log the interaction
        try:
            db.log_interaction(req.tg_user_id, req.platform, req.text, result)
        except Exception as e:
            logger.warning(f"log_interaction failed: {e}")
        
        return ComposeResponse(**result)
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

        # Create ComposeRequest object and call compose function
        compose_req = ComposeRequest(platform=platform, text=complaint_text, business_type=business_type, tg_user_id=tg_user_id)
        result = compose(compose_req)

        logger.info(f"Compose result: {result}")

        # Wrap response in 'response' key for n8n parsing
        return {"response": result.dict()}

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("n8n webhook processing failed")
        raise HTTPException(status_code=500, detail=f"Processing failed: {str(e)}")
