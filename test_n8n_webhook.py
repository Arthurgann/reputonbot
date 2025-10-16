#!/usr/bin/env python3
"""
Test script to verify the n8n webhook endpoint
"""
import asyncio
import httpx
import json

async def test_n8n_webhook():
    # Start the FastAPI server in the background
    import uvicorn
    import threading
    from backend.main import app
    
    def run_server():
        uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")
    
    # Run server in a separate thread
    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()
    
    # Give the server a moment to start
    import time
    time.sleep(2)
    
    # Test the n8n webhook endpoint
    async with httpx.AsyncClient(timeout=30) as client:
        # Example payload from n8n
        payload = {
            "text": "Пользователь оставил негативный отзыв: 'Ваш товар ужасный, вы мошенники!'", 
            "platform": "wildberries",
            "business_type": "e-commerce"
        }
        
        print("Testing n8n webhook endpoint...")
        print(f"Payload: {json.dumps(payload, ensure_ascii=False)}")
        
        try:
            response = await client.post(
                "http://127.0.0.1:8000/webhook/n8n",
                json=payload,
                headers={"Content-Type": "application/json"}
            )
            
            print(f"Status Code: {response.status_code}")
            print(f"Response: {response.text}")
            
            if response.status_code == 200:
                print("✅ n8n webhook test successful!")
                return True
            else:
                print(f"❌ n8n webhook test failed with status {response.status_code}")
                return False
                
        except Exception as e:
            print(f"❌ Error during n8n webhook test: {e}")
            return False

if __name__ == "__main__":
    # For a quick test without starting the server, let's just verify the endpoint exists
    import sys
    import os
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    
    from backend.main import app
    # Check if the endpoint exists
    routes = [route.path for route in app.routes]
    if "/webhook/n8n" in routes:
        print("✅ n8n webhook endpoint exists in the app")
    else:
        print("❌ n8n webhook endpoint not found")
    
    print("Routes available:")
    for route in app.routes:
        print(f"  {route.methods} {route.path}")