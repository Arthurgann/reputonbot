from typing import Optional, Any, Dict
from supabase import create_client, Client
from . import logger
from ..config import settings

_client: Optional[Client] = None

def get_client() -> Client:
    global _client
    if _client is None:
        if not settings.SUPABASE_URL or not settings.SUPABASE_SERVICE_ROLE_KEY:
            raise RuntimeError("Supabase credentials are missing in .env")
        _client = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)
    return _client

def get_platform_prompt(platform: str) -> str:
    sb = get_client()
    res = sb.table("platform_rules").select("system_prompt").eq("platform", platform).single().execute()
    data = res.data
    if not data or "system_prompt" not in data:
        raise ValueError(f"No system_prompt for platform={platform}")
    return data["system_prompt"]

def get_platform_rules(platform: str) -> Dict[str, Any]:
    sb = get_client()
    res = sb.table("platform_rules").select("platform, name, rules, instruction_template, tips, report_url, system_prompt, rules_version").eq("platform", platform).single().execute()
    row = res.data
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

def log_interaction(tg_user_id: Optional[str], platform: str, input_text: str, output_json: Dict[str, Any]) -> None:
    sb = get_client()
    _ = sb.table("interactions").insert({
        "tg_user_id": tg_user_id,
        "platform": platform,
        "input_text": input_text,
        "output_json": output_json
    }).execute()