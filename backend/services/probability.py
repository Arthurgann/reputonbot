from typing import Dict, Any
import re

def score_probability(review_text: str, rules_json: Dict[str, Any]) -> str:
    """
    Calculate probability label based on review text and rules using heuristics.
    
    Args:
        review_text: The text of the review to analyze
        rules_json: The rules dictionary from the database
    
    Returns:
        A probability label: "Низкая", "Средняя", or "Высокая"
    """
    # Convert text to lowercase for analysis
    text_lower = review_text.lower()
    
    # Initialize score counter
    score = 0
    
    # Check for negative sentiment indicators
    negative_indicators = [
        r'оскорблен', r'руга', r'плохо', r'ужас', r'отврат', r'негодован', 
        r'гнев', r'злость', r'сердит', r'ругательств', r'бесит', r'дур',
        r'дура', r'идиот', r'туп', r'глуп', r'мерз', r'гад', r'подл',
        r'ненавид', r'ненавист', r'плохой', r'худший', r'отстой', r'дрянь'
    ]
    
    for indicator in negative_indicators:
        if re.search(indicator, text_lower):
            score += 1
    
    # Check for rule violations
    if isinstance(rules_json, dict):
        for rule_key, rule_value in rules_json.items():
            if isinstance(rule_value, str):
                rule_lower = rule_value.lower()
                if re.search(rule_lower.replace('.', r'\.').replace('?', r'\?').replace('*', r'\*'), text_lower):
                    score += 1
    
    # Check for excessive punctuation or caps
    if re.search(r'[!]{3,}|[?]{3,}', review_text):
        score += 1
    
    if text_lower != review_text and re.search(r'[A-Z]{4,}', review_text):
        score += 1
    
    # Determine probability label based on score
    if score >= 3:
        return "Высокая"
    elif score >= 1:
        return "Средняя"
    else:
        return "Низкая"