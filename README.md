
# ReputonBot Starter (FastAPI + Supabase)

Minimal FastAPI backend to power a Telegram bot (via n8n).

## Local run

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Copy .env.example to .env and fill keys
uvicorn backend.main:app --reload
```

Open: http://127.0.0.1:8000/health
