import os
import argparse
import time
import re
from sqlalchemy import text
from app.models import engine

def normalize_subject(subject):
    if not subject: return ""
    return re.sub(r'[\r\n\t]', ' ', subject).strip()

def recover_subjects_fast(mbox_path):
    print(f"🚑 Starting Subject Recovery from: {mbox_path}")
    
    # Pre-load all Message-IDs to filter
    with engine.connect() as conn:
        print("   - Loading existing Message-IDs...")
        # Map message_id -> pk
        rows = conn.execute(text("SELECT message_id, id FROM messages WHERE subject IS NULL")).fetchall()
        # Clean IDs
        target_mids = {} # raw_str -> pk
        for r in rows:
            target_mids[r[0].strip()] = r[1]
            
        print(f"     -> Need to recover subjects for {len(target_mids)} messages.")
        
    start_time = time.time()
    processed_count = 0
    match_count = 0
    updates = []
    
    # Binary scan for speed
    # Searching for:
    # Message-ID: <...>
    # Subject: ...
    
    # State machine
    # 0: Searching for Header Block (From )
    # 1: Reading Headers
    # inside headers, capture Message-ID and Subject.
    
    print("   - Scanning Mbox (Stream)...")
    
    current_mid = None
    current_subject = None
    in_headers = False
    
    batch_size = 5000
    
    with engine.begin() as conn: # Transaction
        with open(mbox_path, 'rb') as f:
            for line in f:
                try:
                    line_str = line.decode('utf-8', errors='ignore')
                except:
                    continue
                
                if line_str.startswith('From '):
                    # End of previous message
                    if current_mid and current_subject and current_mid in target_mids:
                        # Found a match!
                        pk = target_mids[current_mid]
                        updates.append({'pk': pk, 'sub': current_subject})
                        match_count += 1
                        
                        if len(updates) >= batch_size:
                            conn.execute(
                                text("UPDATE messages SET subject = :sub WHERE id = :pk"),
                                updates
                            )
                            updates = []
                            print(f"     ... updated {match_count}", end='\r')
                            
                    # Reset
                    current_mid = None
                    current_subject = None
                    in_headers = True
                    processed_count += 1
                    if processed_count % 1000 == 0:
                        print(f"     ... scanned {processed_count} msgs, updated {match_count}", end='\r')
                    continue
                
                if not in_headers: continue
                
                if line_str.strip() == "":
                    # End of headers
                    in_headers = False
                    continue
                    
                # Parse Headers (Naive)
                # Handle multi-line headers? Simplicity first: assume single line for ID. 
                # Subject might be multi-line (MIME), but let's grab first line first.
                lower = line_str.lower()
                
                if lower.startswith('message-id:'):
                    # Extract ID
                    val = line_str.split(':', 1)[1].strip()
                    current_mid = val
                    
                elif lower.startswith('subject:'):
                    # Extract Subject
                    val = line_str.split(':', 1)[1].strip()
                    # Handle MIME later if needed, but for now raw text is better than nothing
                    # Actually we should decode MIME words if possible, but python verify time is strict.
                    # Let's clean it slightly.
                    current_subject = val

            # Flush last
            if current_mid and current_subject and current_mid in target_mids:
                 pk = target_mids[current_mid]
                 updates.append({'pk': pk, 'sub': current_subject})
                 match_count += 1
                 
            if updates:
                conn.execute(
                    text("UPDATE messages SET subject = :sub WHERE id = :pk"),
                    updates
                )
    
    print(f"\n✅ Recovery Complete. Updated {match_count} subjects.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mbox_path")
    args = parser.parse_args()
    if os.path.exists(args.mbox_path):
        recover_subjects_fast(args.mbox_path)
