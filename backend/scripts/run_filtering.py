import os
import sys
from sqlalchemy import text
from app.models import engine

def run_filtering():
    print("🧹 Starting filtering process (Phase 1)...")
    
    with engine.connect() as conn:
        # 1. Reset all to active first (optional, but good for idempotency)
        # conn.execute(text("UPDATE threads SET status = 'active'"))
        
        # 2. Filter single-message threads (No conversation)
        print("   - Marking single-message threads as 'ignored'...")
        stmt_single = text("""
            UPDATE threads 
            SET status = 'ignored' 
            WHERE (SELECT count(*) FROM messages WHERE thread_id = threads.id) < 2
            AND status = 'active';
        """)
        result = conn.execute(stmt_single)
        print(f"     -> {result.rowcount} threads ignored (single message).")
        
        # 3. Filter by Headers (Bulk, Notifications)
        print("   - Marking bulk/notification threads as 'ignored'...")
        # Note: metadata_ is JSONB. We check common bulk headers.
        stmt_bulk = text("""
            UPDATE threads
            SET status = 'ignored'
            WHERE status = 'active'
            AND id IN (
                SELECT DISTINCT thread_id FROM messages 
                WHERE metadata_ ->> 'List-Unsubscribe' IS NOT NULL 
                   OR metadata_ ->> 'Precedence' IN ('bulk', 'list', 'junk', 'auto_reply')
                   OR metadata_ ->> 'X-Auto-Response-Suppress' IS NOT NULL
                   OR metadata_ ->> 'Auto-Submitted' != 'no'
            );
        """)
        result = conn.execute(stmt_bulk)
        print(f"     -> {result.rowcount} threads ignored (bulk headers).")
        
        # 4. Filter by Sender Address (No-reply, etc matching)
        # We assume contact.email holds the address.
        print("   - Marking system accounts (noreply, info, etc) as 'ignored'...")
        stmt_system = text("""
            UPDATE threads
            SET status = 'ignored'
            WHERE status = 'active'
            AND contact_id IN (
                SELECT id FROM contacts 
                WHERE email ILIKE '%no-reply%' 
                   OR email ILIKE '%noreply%' 
                   OR email ILIKE '%donotreply%'
                   OR email ILIKE '%checker%'
                   OR email ILIKE '%notification%'
                   OR email ILIKE '%alert%'
                   OR email ILIKE '%bounce%'
                   OR email ILIKE 'support@%'
                   OR email ILIKE 'info@%'
            );
        """)
        result = conn.execute(stmt_system)
        print(f"     -> {result.rowcount} threads ignored (system keywords).")

        # 5. Filter One-Way Communication (Strongest Filter)
        # Threads where only 1 person (sender) is speaking are likely notifications.
        # Real conversations usually involve at least 2 participants (Me + Them, or Them + Them).
        print("   - Marking one-way threads (only 1 unique sender) as 'ignored'...")
        stmt_oneway = text("""
            UPDATE threads
            SET status = 'ignored'
            WHERE status = 'active'
            AND (
                SELECT count(DISTINCT contact_id) 
                FROM messages 
                WHERE thread_id = threads.id
            ) < 2;
        """)
        result = conn.execute(stmt_oneway)
        print(f"     -> {result.rowcount} threads ignored (one-way communication).")
        
        conn.commit()
        
        # Final Stats
        result_active = conn.execute(text("SELECT count(*) FROM threads WHERE status = 'active'"))
        active_count = result_active.scalar()
        
        result_total = conn.execute(text("SELECT count(*) FROM threads"))
        total_count = result_total.scalar()
        
        print("-" * 30)
        print(f"🎯 Filtering Complete.")
        print(f"   Total Threads: {total_count}")
        print(f"   Active Threads (Potential Leads): {active_count}")
        print(f"   Reduction Rate: {100 - (active_count/total_count*100):.1f}%")

if __name__ == "__main__":
    run_filtering()
