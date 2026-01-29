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

# Global flag for graceful shutdown
shutdown_requested = False

def signal_handler(sig, frame):
    global shutdown_requested
    print("\n⚠️  Interrupt received! Finishing current batch and saving progress...")
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

def process_mbox(file_path):
    print(f"Opening mbox: {file_path}")
    print(f"DB Engine: {engine.dialect.name}")
    
    # Ensure tables exist
    create_tables()
    
    session = SessionLocal()
    
    # Load progress
    progress = load_progress()
    skip_count = progress.get("processed_count", 0)
    print(f"🔄 Resuming from message #{skip_count}...")
    
    global shutdown_requested
    current_index = 0
    processed_in_batch = 0
    last_msg_id = progress.get("last_message_id")
    
    try:
        mbox = mailbox.mbox(file_path)
        
        # We have to iterate to skip, but we can do it faster by not parsing full content if possible
        # Mbox iterator yields Message objects, so overhead is there.
        # For huge files, proper skipping is hard without index, but mere iteration is faster than DB insert.
        
        for i, message in enumerate(mbox):
            if shutdown_requested:
                break
                
            # Skip already processed
            if i < skip_count:
                if i % 10000 == 0:
                    print(f"Skipping... currently at {i}/{skip_count}", end='\r')
                continue

            current_index = i
            
            try:
                if not is_human_email(message): continue
                
                msg_id = message.get('Message-ID', '').strip()
                if not msg_id: continue
                
                date_str = message.get('Date')
                if not date_str: continue
                try:
                    sent_at = parsedate_to_datetime(date_str)
                except:
                    continue
                
                from_name, from_addr = parseaddr(message.get('From'))
                
                # Contact
                contact_id = get_or_create_contact(session, from_addr, from_name)
                
                # Simple Threading
                subject = message.get('Subject', '')
                thread = Thread(contact_id=contact_id, subject=subject, last_message_at=sent_at)
                session.add(thread)
                session.flush()
                
                # Metadata extraction
                metadata = {
                    "To": message.get('To'),
                    "Cc": message.get('Cc'),
                    "References": message.get('References'),
                    "In-Reply-To": message.get('In-Reply-To'),
                    "Content-Type": message.get_content_type()
                }

                # Message
                db_msg = Message(
                    thread_id=thread.id,
                    contact_id=contact_id,
                    message_id=msg_id,
                    sender_type='contact',
                    sent_at=sent_at,
                    content_body="Pending extraction",
                    metadata_=metadata
                )
                session.add(db_msg)
                
                processed_in_batch += 1
                last_msg_id = msg_id
                
                if processed_in_batch >= BATCH_SIZE:
                    session.commit()
                    save_progress(current_index + 1, last_msg_id)
                    print(f"✅ Processed {current_index + 1} messages... (Last ID: {last_msg_id})")
                    processed_in_batch = 0
                    
            except Exception as e:
                # print(f"Skipping msg: {e}")
                continue
                
        # Final commit
        session.commit()
        save_progress(current_index + 1, last_msg_id)
        print(f"🎉 Finished! Total processed up to index: {current_index + 1}")
        
    except Exception as e:
        print(f"❌ Critical Error: {e}")
        session.rollback()
    finally:
        session.close()
        if shutdown_requested:
            print("\n🛑 Execution stopped safely. Progress saved.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mbox_path")
    args = parser.parse_args()
    if os.path.exists(args.mbox_path):
        process_mbox(args.mbox_path)
    else:
        print("File not found.")
