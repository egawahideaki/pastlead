import sys
import os
from sqlalchemy import text
from app.models import engine

def run_filtering():
    print("🧹 Starting filtering process (Phase 1)...")
    
    with engine.connect() as conn:
        # Reset all to active first (to allow re-run)
        conn.execute(text("UPDATE threads SET status = 'active'"))
        conn.commit()
        
        # 1. Filter "Too Many Messages" (Likely Newsletters/System Logs)
        # Relaxed threshold to 300 based on user feedback (projects can be large).
        print("   - Marking very high-frequency threads (>300 msgs) as 'ignored'...")
        stmt_high_freq = text("""
            UPDATE threads 
            SET status = 'ignored' 
            WHERE message_count > 300 
            AND status = 'active';
        """)
        result = conn.execute(stmt_high_freq)
        print(f"     -> {result.rowcount} threads ignored (too many messages > 300).")

        # 2. Filter by Sender Email Keywords (Blacklist) - Python Logic for safety
        print("   - Filtering blacklist keywords (Python-side check)...")
        
        blacklist = [
            'no-reply', 'noreply', 'donotreply', 'notification', 'bounces', 
            'alert', 'info@', 'support@', 'newsletter', 'mag2', 'magazine', 
            'news@', 'update@', 'press@', 'editor@', 'seminar@', 'survey@',
            'auto-confirm', 'confirm@', 'account@', 'admin@', 'service@'
        ]
        
        # Fetch all active threads with their contact emails
        # Doing this in Python is slower but 100% reliable compared to SQLite LIKE nuances
        stmt_fetch = text("""
            SELECT t.id, c.email 
            FROM threads t
            JOIN contacts c ON t.contact_id = c.id
            WHERE t.status = 'active'
        """)
        rows = conn.execute(stmt_fetch).fetchall()
        
        ignored_tids = []
        for row in rows:
            tid, email = row
            if not email: continue
            
            email_lower = email.lower()
            for kw in blacklist:
                if kw in email_lower:
                    ignored_tids.append(tid)
                    break
        
        # Batch update ignored threads
        if ignored_tids:
            # Chunking for SQLite limits
            chunk_size = 500
            for i in range(0, len(ignored_tids), chunk_size):
                chunk = ignored_tids[i:i+chunk_size]
                tids_str = ",".join(str(t) for t in chunk)
                conn.execute(text(f"UPDATE threads SET status = 'ignored' WHERE id IN ({tids_str})"))
            
            conn.commit()
            print(f"     -> {len(ignored_tids)} threads ignored (blacklisted keywords).")
        else:
            print("     -> 0 threads ignored.")

    print("------------------------------")
    print("🎯 Filtering Complete.")

    # Calculate stats
    with engine.connect() as conn:
        total = conn.execute(text("SELECT count(*) FROM threads")).scalar()
        active = conn.execute(text("SELECT count(*) FROM threads WHERE status = 'active'")).scalar()
        
        if total > 0:
            reduction = ((total - active) / total) * 100
        else:
            reduction = 0
            
        print(f"   Total Threads: {total}")
        print(f"   Active Threads (Potential Leads): {active}")
        print(f"   Reduction Rate: {reduction:.1f}%")

if __name__ == "__main__":
    run_filtering()
