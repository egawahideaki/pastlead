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

import mailbox
from email.header import decode_header, make_header

def decode_mime_header(header_val):
    if not header_val: return ""
    try:
        # decode_header returns list of (bytes, encoding)
        decoded = decode_header(header_val)
        # make_header converts it to a decent string
        return str(make_header(decoded))
    except:
        return header_val

def recover_subjects_fast(mbox_path):
    print(f"🚑 Starting RELIABLE Subject Recovery from: {mbox_path}")
    
    real_path = resolve_path(mbox_path)
    if not real_path:
        import glob
        matches = glob.glob(mbox_path)
        if matches:
            real_path = matches[0]
        else:
            print(f"❌ Error: {mbox_path} not found.")
            return

    # Pre-load all Message-IDs
    with engine.connect() as conn:
        print("   - Loading existing Message-IDs...")
        rows = conn.execute(text("SELECT message_id, id FROM messages")).fetchall()
        target_mids = {}
        for r in rows:
            # Clean ID: remove angle brackets if present in DB (though DB usually has them)
            # Standardize cleaning for lookup
            mid_key = r[0].strip()
            target_mids[mid_key] = r[1]
            # Also support un-bracketed version just in case
            if mid_key.startswith('<') and mid_key.endswith('>'):
                target_mids[mid_key[1:-1]] = r[1]
            else:
                target_mids[f"<{mid_key}>"] = r[1]
            
        print(f"     -> Target count: {len(target_mids)} messages.")

    processed = 0
    updated = 0
    updates = []
    
    print("   - Iterating Mbox (mailbox module)...")
    
    # Use standard mailbox.mbox which is robust but maybe slower
    mbox = mailbox.mbox(real_path, create=False)
    
    with engine.begin() as conn:
        for message in mbox:
            try:
                mid_raw = message.get('message-id', '').strip()
                if not mid_raw: continue
                
                # Check match
                # Try raw, try cleaned
                pk = None
                if mid_raw in target_mids:
                    pk = target_mids[mid_raw]
                else:
                    # Clean brackets
                    clean = mid_raw.strip('<>')
                    if clean in target_mids:
                        pk = target_mids[clean]
                
                if pk:
                    sub_raw = message.get('subject', '')
                    final_sub = decode_mime_header(sub_raw)
                    
                    updates.append({'pk': pk, 'sub': final_sub})
                    updated += 1
                    
                    if len(updates) >= 1000:
                        conn.execute(
                            text("UPDATE messages SET subject = :sub WHERE id = :pk"),
                            updates
                        )
                        updates = []
                        print(f"     ... updated {updated}", end='\r')
            
            except Exception as e:
                # Malformed message?
                continue
                
            processed += 1
            if processed % 1000 == 0:
                 print(f"     ... scanned {processed}, found {updated}", end='\r')
                 
        # Final flush
        if updates:
             conn.execute(
                text("UPDATE messages SET subject = :sub WHERE id = :pk"),
                updates
            )
            
    print(f"\n✅ Recovery Complete. Updated {updated} subjects.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mbox_path")
    args = parser.parse_args()
    recover_subjects_fast(args.mbox_path)
