import sys
import os

# Adjust path for import
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.ai_summary import generate_thread_summary

if __name__ == "__main__":
    test_messages = [
        {"sender_name": "Target Company CEO", "date": "2024-01-20", "body": "We are interested in your proposal. Can we discuss the pricing?"},
        {"sender_name": "Me", "date": "2024-01-21", "body": "Sure, I can offer a 10% discount if we sign this month."},
        {"sender_name": "Target Company CEO", "date": "2024-01-22", "body": "Sounds good. Please send the updated contract by Friday."}
    ]
    
    print("Testing AI Summary with gemma3n:e2b...")
    
    # Run slightly differently to show progress
    try:
        import requests
        requests.get("http://localhost:11434", timeout=1)
        print("Ollama is reachable.")
    except:
        print("WARNING: Is Ollama running?")

    result = generate_thread_summary(test_messages)
    import json
    print(json.dumps(result, indent=2, ensure_ascii=False))
