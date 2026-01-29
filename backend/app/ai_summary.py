
import requests
import json
import os
from typing import List, Dict, Any

# --- Configuration ---
# 'ollama' or 'gemini'
AI_PROVIDER = os.getenv("AI_PROVIDER", "ollama").lower()

# Ollama Settings
OLLAMA_HOST = "http://127.0.0.1:11434"
OLLAMA_MODEL = "gemma3n:e2b"

# Gemini Settings
GEMINI_API_KEY = os.getenv("GOOGLE_API_KEY")
# Default to Flash for speed, user can override to 'gemini-1.5-pro' etc.
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash") 

# --- Helper Functions ---

def clean_email_body(text: str) -> str:
    """
    Remove quoted text (> lines) and potential signatures/footers to reduce token usage.
    """
    if not text:
        return ""
        
    lines = text.split('\n')
    cleaned_lines = []
    
    for line in lines:
        line_stripped = line.strip()
        # Skip quoted lines
        if line_stripped.startswith('>') or line_stripped.startswith('＞'):
            continue
        # Skip likely separator lines often used before signatures
        if set(line_stripped) <= {'-', '_', '=', '*'}:
             # If line is just separators and longer than 3 chars
            if len(line_stripped) > 3:
                continue
                
        cleaned_lines.append(line)
        
    return '\n'.join(cleaned_lines)

def build_prompt(messages: List[Dict[str, Any]]) -> str:
    prompt = f"""
    あなたは優秀な営業アシスタントAIです。以下のメールスレッド（時系列順）を分析し、
    以下の情報を抽出してJSON形式で回答してください。引用部分（>）は削除されています。
    必ず有効なJSONのみを出力してください。余計な説明文は一切不要です。
    JSONのキー名は必ず小文字にしてください。

    【入力データ: メールスレッド】
    """
    
    for msg in messages:
        # Check message type (default to full if not specified)
        msg_type = msg.get("type", "full")
        
        if msg_type == "summary":
             # Already shortened snippet
             prompt += f"\n- 送信者: {msg['sender_name']} ({msg['date']})\n  [中略] {msg['body']}\n"
        else:
             # Full message: Pre-process body to remove noise
            cleaned_body = clean_email_body(msg['body'])
            if not cleaned_body.strip():
                 continue
                 
            # Use a more generous limit for Gemini (basically unlimited) vs Ollama
            limit = 10000 if AI_PROVIDER == 'gemini' else 1000
            prompt += f"\n- 送信者: {msg['sender_name']} ({msg['date']})\n  本文: {cleaned_body[:limit]}\n"

    prompt += """
    
    【出力フォーマット (JSON)】
    {
        "status": "現在の状況（例：提案中、返信待ち、失注、成約）",
        "summary": "スレッド全体の要約（150文字以内）",
        "next_action": "次に取るべきアクション（例：〇〇について返信する、日程調整を送る）",
        "key_person": "キーマン・決裁権者と思われる人物（いなければ不明）",
        "sentiment": "相手の感情（Positive, Neutral, Negative, Angry等）",
        "urgency": "緊急度（High, Medium, Low）"
    }

    JSON:
    """
    return prompt

def generate_with_ollama(prompt: str) -> Dict[str, Any]:
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "format": "json" 
    }
    try:
        # Increased timeout to 180 seconds
        response = requests.post(f"{OLLAMA_HOST}/api/generate", json=payload, timeout=180)
        response.raise_for_status()
        
        result = response.json()
        generated_text = result.get("response", "").strip()
        print(f"DEBUG: Ollama Raw Output: {generated_text}")
        return parse_json_response(generated_text)
            
    except requests.exceptions.Timeout:
        print("Ollama Request Timed Out")
        return {"summary": "Analysis timed out (Ollama). Try Gemini for speed.", "status": "Timeout"}
    except Exception as e:
        print(f"Ollama Generic Error: {e}")
        return {"summary": f"Error: {str(e)}", "status": "Error"}

def generate_with_gemini(prompt: str) -> Dict[str, Any]:
    if not GEMINI_API_KEY:
        return {"summary": "Google API Key not set.", "status": "Config Error"}
        
    try:
        import google.generativeai as genai
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel(GEMINI_MODEL)
        
        # Gemini 1.5/2.0 supports JSON mode natively via generation_config
        generation_config = {"response_mime_type": "application/json"}
        
        response = model.generate_content(prompt, generation_config=generation_config)
        generated_text = response.text.strip()
        print(f"DEBUG: Gemini Raw Output: {generated_text}")
        
        return parse_json_response(generated_text)
        
    except Exception as e:
        print(f"Gemini Error: {e}")
        return {"summary": f"Gemini Error: {str(e)}", "status": "Error"}

def parse_json_response(generated_text: str) -> Dict[str, Any]:
    try:
        # Cleanup markdown block if present
        if generated_text.startswith("```json"):
            generated_text = generated_text.replace("```json", "").replace("```", "")
        elif generated_text.startswith("```"):
            generated_text = generated_text.replace("```", "")
        
        # Remove any trailing junk like "JSON:" again
        if "JSON:" in generated_text:
             parts = generated_text.split("JSON:")
             if len(parts) > 1 and parts[1].strip().startswith("{"):
                 generated_text = parts[1]

        data = json.loads(generated_text)
        
        # Normalize keys to lower case
        normalized_data = {k.lower(): v for k, v in data.items()}
        
        final_data = {
            "summary": normalized_data.get("summary", normalized_data.get("summaary", "No summary generated.")),
            "status": normalized_data.get("status", "Unknown"),
            "next_action": normalized_data.get("next_action", normalized_data.get("nextaction", "None")),
            "key_person": normalized_data.get("key_person", normalized_data.get("keyperson", "Unknown")),
            "sentiment": normalized_data.get("sentiment", "Neutral"),
            "urgency": normalized_data.get("urgency", "Medium")
        }
        return final_data

    except json.JSONDecodeError:
        print(f"JSON Decode Error. Raw output: {generated_text}")
        return {
            "summary": f"Parse Error. Content: {generated_text[:100]}...",
            "status": "Analysis Failed"
        }

def generate_thread_summary(messages: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Generates a summary using the configured AI provider.
    """
    if not messages:
        return {"summary": "No messages to analyze.", "next_action": "None", "sentiment": "Neutral"}

    prompt = build_prompt(messages)
    
    if AI_PROVIDER == 'gemini':
        return generate_with_gemini(prompt)
    else:
        return generate_with_ollama(prompt)
