from app.models import engine
from sqlalchemy import text
import re

def rigorous_cleanup():
    print("🛡️ Starting Rigorous Spam Filtering (Python-based)...")
    
    with engine.connect() as conn:
        # 1. Fetch all contacts with positive scores
        # We target contacts directly because if the contact is spam, all their threads are spam.
        stmt = text("SELECT id, email FROM contacts WHERE closeness_score > 0 OR closeness_score IS NULL")
        contacts = conn.execute(stmt).fetchall()
        
        print(f"   -> Scanning {len(contacts)} contacts...")
        
        # Define strict regex patterns for spam
        # Using regex allows for more complex rules than simple substring match
        spam_patterns = [
            r"no-?reply", r"notification", r"donotreply", r"alert",
            r"info@", r"support@", r"newsletter", r"magazine", 
            r"news@", r"update@", r"press@", r"editor@", 
            r"seminar", r"survey", r"auto-?confirm", r"account@", 
            r"admin@", r"service@", r"bouce", r"mailer-daemon",
            r"system@", r"mailmag", r"campaign"
        ]
        
        spam_contact_ids = []
        
        for cid, email in contacts:
            if not email: continue
            email_lower = email.lower()
            
            for pat in spam_patterns:
                if re.search(pat, email_lower):
                    spam_contact_ids.append(cid)
                    break
        
        print(f"   -> Found {len(spam_contact_ids)} spam contacts.")
        
        # 2. Batch Nuke
        if spam_contact_ids:
            chunk_size = 500
            total_threads_nuked = 0
            
            # Just ignore threads for these contacts
            for i in range(0, len(spam_contact_ids), chunk_size):
                chunk = spam_contact_ids[i:i+chunk_size]
                chunk_str = ",".join(str(c) for c in chunk)
                
                # A. Set threads to ignored
                stmt_threads = text(f"""
                    UPDATE threads 
                    SET status = 'ignored', score = 0 
                    WHERE contact_id IN ({chunk_str})
                """)
                res = conn.execute(stmt_threads)
                total_threads_nuked += res.rowcount
                
                # B. Set contact score to 0
                stmt_contacts = text(f"""
                    UPDATE contacts
                    SET closeness_score = 0
                    WHERE id IN ({chunk_str})
                """)
                conn.execute(stmt_contacts)
                
            print(f"   -> Nuked {total_threads_nuked} threads from spam contacts.")
            conn.commit()
            
        print("✅ Rigorous Cleanup Complete.")

if __name__ == "__main__":
    rigorous_cleanup()
