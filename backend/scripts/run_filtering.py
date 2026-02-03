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

        # 2. Filter by Sender Email Keywords (Blacklist)
        print("   - Marking bulk/notification threads as 'ignored'...")
        
        blacklist = [
            'no-reply', 'noreply', 'donotreply', 'notification', 'bounces', 
            'alert', 'info@', 'support@', 'newsletter', 'mag2', 'magazine', 
            'news@', 'update@', 'press@', 'editor@', 'seminar@', 'survey@',
            'auto-confirm', 'confirm@', 'account@', 'admin@', 'service@'
        ]
        
        # Build OR clauses for LIKE
        # Using simple loop to avoid complex SQL generation issues in SQLite
        print(f"     -> Filtering blacklist keywords: {len(blacklist)} words...")
        
        count = 0
        for word in blacklist:
            stmt_blk = text(f"""
                UPDATE threads 
                SET status = 'ignored' 
                WHERE contact_id IN (
                    SELECT id FROM contacts WHERE email LIKE '%{word}%'
                ) AND status = 'active';
            """)
            res = conn.execute(stmt_blk)
            count += res.rowcount
            
        print(f"     -> {count} threads ignored (blacklisted keywords).")
        
        conn.commit()

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
