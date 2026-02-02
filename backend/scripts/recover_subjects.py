import os
import argparse
import time
import re
from sqlalchemy import text
from app.models import engine

import unicodedata
from email.header import decode_header, make_header

def resolve_path(path_str):
    """
    Handle Mac/Linux unicode normalization differences (NFC vs NFD).
    """
    if os.path.exists(path_str):
        return path_str
    
    dir_name = os.path.dirname(path_str)
    base_name = os.path.basename(path_str)
    
    if not os.path.exists(dir_name):
        return None
        
    normalized_target = unicodedata.normalize('NFC', base_name)
    
    for f in os.listdir(dir_name):
        f_nfc = unicodedata.normalize('NFC', f)
        if f_nfc == normalized_target:
            return os.path.join(dir_name, f)
    return None

def decode_mime_subject(raw_subject):
    try:
        # Decode MIME header
        decoded_fragments = decode_header(raw_subject)
        subject_str = ""
        for bytes_segment, encoding in decoded_fragments:
            if isinstance(bytes_segment, bytes):
                if encoding:
                    try:
                        subject_str += bytes_segment.decode(encoding, errors='ignore')
                    except:
                        subject_str += bytes_segment.decode('utf-8', errors='ignore')
                else:
                    # No encoding specified, try utf-8 or just ascii
                    subject_str += bytes_segment.decode('utf-8', errors='ignore')
            else:
                subject_str += str(bytes_segment)
        return subject_str.strip()
    except:
        return raw_subject

def recover_subjects_fast(mbox_path):
    print(f"🚑 Starting Subject Recovery from: {mbox_path}")
    
    real_path = resolve_path(mbox_path)
    if not real_path:
        # Wildcard handling usually done by shell, but if passed string literal with *...
        import glob
        matches = glob.glob(mbox_path)
        if matches:
            real_path = matches[0]
        else:
            print(f"❌ Error: {mbox_path} not found.")
            return

    print(f"   - Resolved Path: {real_path}")

    # Pre-load all Message-IDs to filter
    with engine.connect() as conn:
        print("   - Loading existing Message-IDs...")
        # Map message_id -> pk
        # We process ALL messages to ensure subjects are correct (some might be raw MIME)
        # But to save time, only process NULL ones first? 
        # No, let's process ALL. Because current DB might have NULLs.
        rows = conn.execute(text("SELECT message_id, id FROM messages")).fetchall()
        # Clean IDs
        target_mids = {} # raw_str -> pk
        for r in rows:
            target_mids[r[0].strip()] = r[1]
            
        print(f"     -> Target count: {len(target_mids)} messages.")
        
    start_time = time.time()
    processed_count = 0
    match_count = 0
    updates = []
    
    print("   - Scanning Mbox (Stream)...")
    
    current_mid = None
    current_subject = None
    in_headers = False
    
    batch_size = 5000
    
    # Pre-compile regex
    re_mid = re.compile(r'^message-id:\s*(<[^>]+>)', re.IGNORECASE)
    re_sub = re.compile(r'^subject:\s*(.+)', re.IGNORECASE)
    
    with engine.begin() as conn: # Transaction
        with open(real_path, 'rb') as f:
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
                        
                        # Decode MIME
                        final_sub = decode_mime_subject(current_subject)
                        
                        updates.append({'pk': pk, 'sub': final_sub})
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
                    in_headers = False
                    continue
                    
                # Regex Parsing (Better than startswith for spacing)
                m_mid = re_mid.match(line_str)
                if m_mid:
                    current_mid = m_mid.group(1).strip()
                    continue
                
                m_sub = re_sub.match(line_str)
                if m_sub:
                    current_subject = m_sub.group(1).strip()
                    continue

            # Flush last
            if current_mid and current_subject and current_mid in target_mids:
                 pk = target_mids[current_mid]
                 final_sub = decode_mime_subject(current_subject)
                 updates.append({'pk': pk, 'sub': final_sub})
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
    recover_subjects_fast(args.mbox_path)
