from app.models import engine
from sqlalchemy import text

def cleanup_spam():
    print("🔥 Starting Emergency Spam Cleanup...")
    
    with engine.connect() as conn:
        # 1. Force IGNORE all threads from blacklisted emails (SQL pattern match)
        # Using simple pattern matching that works in SQLite
        blacklist_patterns = [
            '%no-reply%', '%noreply%', '%donotreply%', '%notification%', 
            '%info@%', '%support@%', '%newsletter%', '%magazine%', '%news@%', 
            '%update@%', '%press@%', '%mag2%', '%survey%'
        ]
        
        print("   - Nuking blacklisted threads directly via SQL...")
        total_nuked = 0
        for pat in blacklist_patterns:
            # Case insensitive LIKE via conversion (SQLite default LIKE is case-insensitive for ASCII, but let's be sure)
            stmt = text(f"""
                UPDATE threads 
                SET status = 'ignored', score = 0
                WHERE contact_id IN (
                    SELECT id FROM contacts WHERE email LIKE '{pat}'
                )
            """)
            res = conn.execute(stmt)
            total_nuked += res.rowcount
            
        print(f"     -> Affected matches (overlap included): {total_nuked}")
        
        # 2. Reset scores for contacts who have NO active threads
        print("   - Resetting contact scores...")
        conn.execute(text("UPDATE contacts SET closeness_score = 0"))
        
        # 3. Re-calculate scores for only valid contacts
        update_stmt = text("""
            UPDATE contacts
            SET closeness_score = (
                SELECT IFNULL(SUM(score), 0) 
                FROM threads 
                WHERE threads.contact_id = contacts.id 
                AND threads.status = 'active'
            )
            WHERE id IN (
                SELECT contact_id FROM threads WHERE status = 'active'
            )
        """)
        conn.execute(update_stmt)
        conn.commit()
        
    print("✅ Cleanup Complete. Please refresh your browser.")

if __name__ == "__main__":
    cleanup_spam()
