
# ReputonBot Backend

Backend for the ReputonBot - a Telegram bot that helps users compose complaints against reviews on various platforms.

## API Endpoints

- `POST /compose` - Main endpoint for complaint composition
- `POST /webhook/n8n` - Webhook for n8n integration
- `GET /health` - Health check endpoint
- `POST /state/set` - Save chat state with selected platform
- `POST /compose_from_state` - Compose response based on platform stored in chat state

## Environment Variables

- `SUPABASE_URL` - Supabase project URL
- `SUPABASE_SERVICE_ROLE_KEY` - Supabase service role key
- `OPENAI_API_KEY` - OpenAI API key

## Running the Application

1. Install dependencies: `pip install -r requirements.txt`
2. Set up environment variables
3. Run the application: `uvicorn backend.main:app --reload`

## Database Setup

The application uses Supabase as its database. The schema is defined in `supabase_bootstrap.sql`.

## New State-Based Flow

The application now supports a new workflow where the platform selection is stored in the database and used for subsequent requests:

1. User selects a platform (e.g., via inline buttons in Telegram bot)
2. Bot calls `POST /state/set` to save the selected platform for the chat
3. User sends complaint text
4. Bot calls `POST /compose_from_state` which retrieves the platform from database and processes the complaint

### New Endpoints Usage

#### `/state/set`
Save platform selection for a chat:
```bash
curl -X POST http://localhost:8000/state/set \
  -H "Content-Type": "application/json" \
  -d '{"chat_id": 11222333, "platform": "ozon"}'
```

#### `/compose_from_state`
Process complaint using stored platform:
```bash
curl -X POST http://localhost:8000/compose_from_state \
  -H "Content-Type": "application/json" \
  -d '{"chat_id": 11222333, "text": "пользовательский текст"}'
```

### Payload Examples

**POST /state/set:**
```json
{
  "chat_id": 11222333,
 "platform": "ozon"
}
```

**POST /compose_from_state:**
```json
{
  "chat_id": 1122233,
  "text": "пользовательский текст"
}
```

## Architecture

The application is built with FastAPI and follows a modular structure:

- `main.py` - Main application with endpoints
- `models/` - Pydantic models
- `services/` - Business logic and database operations
- `routes/` - Additional routes (if any)
