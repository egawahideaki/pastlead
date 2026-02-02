
from sqlalchemy import text
from app.models import engine
import sys

def debug_thread(thread_id):
    print(f"🔍 Analyzing Thread ID: {thread_id}")
    
    with engine.connect() as conn:
        # Get all messages in this thread
        stmt = text("""
            SELECT id, message_id, metadata_->>'In-Reply-To', metadata_->>'References', subject, sent_at
            FROM messages
            WHERE thread_id = :tid
            ORDER BY sent_at ASC
        """)
        msgs = conn.execute(stmt, {"tid": thread_id}).fetchall()
        
        print(f"Found {len(msgs)} messages.")
        print(f"{'PK':<6} | {'Subject':<30} | {'Message-ID':<40} | {'In-Reply-To'}")
        print("-" * 100)
        
        for m in msgs:
            pk = m[0]
            mid = m[1] or ""
            reply = m[2] or ""
            subj = (m[4] or "")[:28]
            
            print(f"{pk:<6} | {subj:<30} | {mid[:38]:<40} | {reply[:40]}")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        debug_thread(int(sys.argv[1]))
    else:
        print("Usage: python debug_thread.py <thread_id>")
