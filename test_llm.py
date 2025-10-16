#!/usr/bin/env python3
"""
Test script to verify the LLM service integration with OpenAI API
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.services.llm import compose_text

def test_llm_service():
    # Example system prompt (this would normally come from Supabase)
    system_prompt = """
    Ты ассистент, который помогает пользователям составлять жалобы на отзывы или комментарии.
    Пользователь предоставит текст жалобы, и ты должен:
    1. Сформулировать корректный текст жалобы
    2. Дать инструкцию как подать жалобу на платформе
    3. Предоставить полезные советы
    Ответ должен быть в формате JSON с полями: complaint, instruction, tips[]
    """
    
    # Example user complaint text
    user_text = "Пользователь написал оскорбительный комментарий: 'Ваш товар ужасный, вы мошенники!'"
    
    print("Testing LLM service with OpenAI API...")
    print(f"System prompt: {system_prompt[:100]}...")
    print(f"User text: {user_text}")
    print("-" * 50)
    
    try:
        result = compose_text(system_prompt, user_text, "e-commerce")
        print("API call successful!")
        print(f"Complaint: {result['complaint']}")
        print(f"Instruction: {result['instruction']}")
        print(f"Tips: {result['tips']}")
    except Exception as e:
        print(f"Error occurred: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_llm_service()