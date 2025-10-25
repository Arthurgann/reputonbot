import pytest
import asyncio
from httpx import AsyncClient
from backend.main import app
from backend.services import db

@pytest.mark.asyncio
async def test_state_set_and_compose_from_state():
    """Test the new state management endpoints"""
    async with AsyncClient(app=app, base_url="http://test") as ac:
        # Test /state/set endpoint
        chat_id = 11122333
        platform = "ozon"
        
        response = await ac.post("/state/set", json={"chat_id": chat_id, "platform": platform})
        assert response.status_code == 200
        assert response.json()["chat_id"] == chat_id
        assert response.json()["platform"] == platform
        
        # Test /compose_from_state without state (should fail)
        response = await ac.post("/compose_from_state", json={"chat_id": 9999, "text": "test complaint"})
        assert response.status_code == 400
        assert "platform_not_selected" in response.json()["detail"]["error"]
        
        # Test /compose_from_state with state (should succeed)
        response = await ac.post("/compose_from_state", json={"chat_id": chat_id, "text": "пользовательский текст"})
        assert response.status_code == 200
        
        # Verify response structure
        data = response.json()
        assert "complaint" in data
        assert "instruction" in data
        assert "tips" in data
        assert isinstance(data["tips"], list)

@pytest.mark.asyncio
async def test_compose_function():
    """Test the internal compose function"""
    # This tests the internal function that both /compose and /compose_from_state use
    from backend.main import compose_async
    
    result = await compose_async("ozon", "пользовательский текст", "11222333")
    
    assert "complaint" in result
    assert "instruction" in result
    assert "tips" in result
    assert isinstance(result["tips"], list)
    assert "probability_label" in result

if __name__ == "__main__":
    pytest.main([__file__])