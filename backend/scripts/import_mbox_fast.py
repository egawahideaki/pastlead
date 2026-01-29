import mailbox
import email
from email.utils import parseaddr, parsedate_to_datetime
import os
import argparse
from sqlalchemy.orm import Session
from app.models import engine, SessionLocal, Contact, Thread, Message, create_tables
from sqlalchemy.dialects.postgresql import insert
from datetime import datetime
import json
import signal
import sys
import time

BATCH_SIZE = 1000
PROGRESS_FILE = "import_progress.json"
IGNORE_DOMAINS = ["noreply", "no-reply", "donotreply", "notification", "info", "mailer-daemon"]

shutdown_requested = False

def signal_handler(sig, frame):
    global shutdown_requested
    print("\n⚠️  Interrupt received! Finishing current batch...")
    shutdown_requested = True

signal.signal(signal.SIGINT, signal_handler)

def load_progress():
    if os.path.exists(PROGRESS_FILE):
        try:
            with open(PROGRESS_FILE, 'r') as f:
                return json.load(f)
        except:
            return {"processed_count": 0, "last_message_id": None}
    return {"processed_count": 0, "last_message_id": None}

def save_progress(count, last_msg_id):
    with open(PROGRESS_FILE, 'w') as f:
        json.dump({"processed_count": count, "last_message_id": last_msg_id}, f)

def is_valid_email(email_addr):
    if not email_addr: return False
    if any(ignore in email_addr.lower() for ignore in IGNORE_DOMAINS): return False
    return True

def is_human_email(msg):
    if 'List-Unsubscribe' in msg: return False
    if 'Precedence' in msg and msg['Precedence'] in ['bulk', 'list', 'junk']: return False
    from_header = msg.get('From')
    if not from_header: return False
    name, addr = parseaddr(from_header)
    if not is_valid_email(addr): return False
    return True

def get_or_create_contact(session, email_addr, name):
    stmt = insert(Contact).values(
        email=email_addr, name=name, closeness_score=0
    ).on_conflict_do_update(
        index_elements=['email'],
        set_=dict(name=name, updated_at=datetime.now())
    ).returning(Contact.id)
    return session.execute(stmt).scalar()

def process_message_data(session, msg_bytes):
    try:
        # Parse only headers first if possible? No, bytes parser does all.
        message = email.message_from_bytes(msg_bytes)
        
        if not is_human_email(message): return False, None
        
        msg_id = message.get('Message-ID', '').strip()
        if not msg_id: return False, None
        
        date_str = message.get('Date')
        if not date_str: return False, None
        try:
            sent_at = parsedate_to_datetime(date_str)
        except:
            return False, None
            
        from_name, from_addr = parseaddr(message.get('From'))
        contact_id = get_or_create_contact(session, from_addr, from_name)
        
        subject = message.get('Subject', '')
        # Thread creation (Naive)
        thread = Thread(contact_id=contact_id, subject=subject, last_message_at=sent_at)
        session.add(thread)
        session.flush()
        
        metadata = {
            "To": message.get('To'),
            "Cc": message.get('Cc'),
            "References": message.get('References'),
            "In-Reply-To": message.get('In-Reply-To'),
            "Content-Type": message.get_content_type()
        }

        # Use UPSERT (Do Nothing on Conflict) to handle duplicate Message-IDs in mbox
        stmt = insert(Message).values(
            thread_id=thread.id,
            contact_id=contact_id,
            message_id=msg_id,
            sender_type='contact',
            sent_at=sent_at,
            content_body="Pending extraction",
            metadata_=metadata
        ).on_conflict_do_nothing()
        session.execute(stmt)
        
        return True, msg_id
    except Exception as e:
        # print(f"Error parsing msg: {e}")
        return False, None

def process_mbox_fast(file_path):
    print(f"Opening mbox (Fast Mode): {file_path}")
    print(f"DB Engine: {engine.dialect.name}")
    create_tables()
    session = SessionLocal()
    
    progress = load_progress()
    skip_count = progress.get("processed_count", 0)
    print(f"🔄 Resuming from message #{skip_count}...")
    
    current_index = 0
    processed_in_batch = 0
    last_msg_id = progress.get("last_message_id")
    
    start_time = time.time()
    
    try:
        with open(file_path, 'rb') as f:
            buffer = []
            for line in f:
                if shutdown_requested: break
                
                if line.startswith(b'From '):
                    if buffer:
                        # Process previous message
                        if current_index >= skip_count:
                             success, mid = process_message_data(session, b''.join(buffer))
                             if success:
                                 processed_in_batch += 1
                                 last_msg_id = mid
                             
                             if processed_in_batch >= BATCH_SIZE:
                                 session.commit()
                                 save_progress(current_index + 1, last_msg_id)
                                 
                                 elapsed = time.time() - start_time
                                 rate = (current_index - skip_count + 1) / elapsed if elapsed > 0 else 0
                                 print(f"✅ Processed {current_index + 1} messages... (Rate: {rate:.1f} msg/s)")
                                 
                                 processed_in_batch = 0
                        else:
                             # Skipping
                             if current_index % 10000 == 0:
                                 print(f"Skipping {current_index}...", end='\r')
                                
                        current_index += 1
                        buffer = []
                buffer.append(line)
            
            # Last message
            if buffer and current_index >= skip_count and not shutdown_requested:
                success, mid = process_message_data(session, b''.join(buffer))
                if success:
                    processed_in_batch += 1
                    last_msg_id = mid
                            
        session.commit()
        save_progress(current_index + 1, last_msg_id)
        print(f"🎉 Finished! Total processed: {current_index + 1}")
        
    except Exception as e:
        print(f"❌ Critical Error: {e}")
        import traceback
        traceback.print_exc()
        session.rollback()
    finally:
        session.close()
        if shutdown_requested:
            print("\n🛑 Stopped safely.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mbox_path")
    args = parser.parse_args()
    if os.path.exists(args.mbox_path):
        process_mbox_fast(args.mbox_path)
    else:
        print("File not found.")
