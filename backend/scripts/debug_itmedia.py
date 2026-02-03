from app.models import engine
from sqlalchemy import text

def debug_target():
    print("🔍 Debugging ITmedia (or similar high-score contact)...")
    
    with engine.connect() as conn:
        # 1. Find the contact with score ~24.5
        stmt = text("SELECT id, name, email, closeness_score FROM contacts WHERE closeness_score > 20 LIMIT 1")
        contact = conn.execute(stmt).fetchone()
        
        if not contact:
            print("❌ No high score contact found. Maybe score IS reset?")
            return

        cid, name, email, score = contact
        print(f"🎯 Target Contact: {name} <{email}>")
        print(f"   Current Global Score: {score}")
        
        # 2. Check its threads
        stmt_threads = text(f"""
            SELECT id, subject, message_count, score, status 
            FROM threads 
            WHERE contact_id = {cid} AND status = 'active'
            ORDER BY score DESC
            LIMIT 10
        """)
        threads = conn.execute(stmt_threads).fetchall()
        
        print(f"   Active Threads Breakdown (Top 10):")
        total_calc = 0
        for t in threads:
            print(f"     - [ID:{t[0]}] Score: {t[3]} | Msgs: {t[2]} | Subj: {t[1][:30]}...")
            total_calc += (t[3] or 0)
            
        print(f"   Calculated Sum from Active Threads: {total_calc}")
        
        # 3. Check Messages of the Top Thread
        if threads:
            top_tid = threads[0][0]
            print(f"   \n🔎 Inspecting Top Thread [ID:{top_tid}]...")
            msgs = conn.execute(text(f"SELECT sender_type, contact_id FROM messages WHERE thread_id = {top_tid} LIMIT 5")).fetchall()
            senders = set(m[1] for m in msgs)
            print(f"     - Message Sample Senders: {senders}")
            print(f"     - Unique Senders Count: {len(senders)}")

if __name__ == "__main__":
    debug_target()
