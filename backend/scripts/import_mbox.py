import sys
import os
import mailbox
import re
import math
import hashlib
import json
import email
from email.header import decode_header, make_header
from email.utils import parseaddr, parsedate_to_datetime
from bs4 import BeautifulSoup
import unicodedata
import argparse

# Add parent directory to path to allow importing app.models
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.models import engine, Base, Contact, Thread, Message
from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy import text, func

BATCH_SIZE = 1000

# --- Helper Functions ---

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
    
    try:
        for f in os.listdir(dir_name):
            f_nfc = unicodedata.normalize('NFC', f)
            if f_nfc == normalized_target:
                return os.path.join(dir_name, f)
    except FileNotFoundError:
        return None
        
    return None

def decode_mime_header(header_val):
    if not header_val: return ""
    try:
        decoded = decode_header(header_val)
        return str(make_header(decoded))
    except:
        return header_val

def clean_quote(text_body):
    """
    Remove quoted text (starting with >), and signature blocks/forwarding headers.
    """
    if not text_body: return ""
    
    lines = text_body.split('\n')
    cleaned_lines = []
    
    # Common quote headers
    quote_headers = [
        re.compile(r'^On\s.*wrote:', re.IGNORECASE),
        re.compile(r'^---+\s*Original Message\s*---+', re.IGNORECASE),
        re.compile(r'^From:\s', re.IGNORECASE), # Often starts a forward block
        re.compile(r'^Sent from my iPhone', re.IGNORECASE),
        re.compile(r'^Sent from my Android', re.IGNORECASE)
    ]
    
    for line in lines:
        sline = line.strip()
        
        # 1. Skip lines starting with >
        if sline.startswith('>'):
            continue
            
        # 2. Check for quote headers
        is_quote_header = False
        for qh in quote_headers:
            if qh.match(sline):
                # If "On ... wrote:", assume rest is quote
                if sline.lower().startswith("on ") and sline.endswith("wrote:"):
                     return "\n".join(cleaned_lines).strip()
                
                # If "Original Message", assume rest is quote
                if "original message" in sline.lower():
                     return "\n".join(cleaned_lines).strip()

                # iPhone signature -> Cut rest
                if "Sent from my" in sline:
                    return "\n".join(cleaned_lines).strip()

        cleaned_lines.append(line)
        
    return "\n".join(cleaned_lines).strip()

def extract_body(message):
    """
    Extract logic: Prefer plain text, fall back to HTML (stripped).
    """
    body_text = ""
    
    if message.is_multipart():
        # Iterate parts
        for part in message.walk():
            # content-disposition check?
            if part.get_content_maintype() == 'text':
                payload = part.get_payload(decode=True)
                if not payload: continue
                
                charset = part.get_content_charset() or 'utf-8'
                try:
                    text_chunk = payload.decode(charset, errors='ignore')
                except:
                    text_chunk = payload.decode('utf-8', errors='ignore')
                
                subtype = part.get_content_subtype()
                if subtype == 'plain':
                    body_text = text_chunk
                    break # Found plain text, good enough
                elif subtype == 'html':
                    # Fallback if no plain found yet
                    if not body_text:
                        soup = BeautifulSoup(text_chunk, 'lxml')
                        body_text = soup.get_text('\n')
    else:
        # Single part
        payload = message.get_payload(decode=True)
        if payload:
            charset = message.get_content_charset() or 'utf-8'
            try:
                body_text = payload.decode(charset, errors='ignore')
            except:
                body_text = payload.decode('utf-8', errors='ignore')
                
            # If HTML, strip
            if message.get_content_subtype() == 'html':
                soup = BeautifulSoup(body_text, 'lxml')
                body_text = soup.get_text('\n')

    return clean_quote(body_text)


def process_mbox(file_path, session):
    print(f"📂 Processing Mbox: {file_path}")
    
    real_path = resolve_path(file_path)
    if not real_path:
        print(f"❌ File not found (unicode issue?): {file_path}")
        return
        
    mbox = mailbox.mbox(real_path, create=False)
    
    count = 0
    buffer_contacts = {} # email -> name
    buffer_messages = []
    
    # Pre-fetch existing contacts to avoid dup errors if upsert not supported (we use upsert though)
    
    for message in mbox:
        try:
            # 1. Parse Headers
            msg_id = message.get('Message-ID', '').strip()
            if not msg_id: continue # Skip messages without ID
            
            # Clean ID
            if msg_id.startswith('<') and msg_id.endswith('>'):
                msg_id = msg_id[1:-1]
            
            subject = decode_mime_header(message.get('Subject', ''))
            
            from_hdr = decode_mime_header(message.get('From', ''))
            to_hdr = decode_mime_header(message.get('To', ''))
            date_hdr = message.get('Date', '')
            
            in_reply_to = message.get('In-Reply-To', '').strip()
            references = message.get('References', '').strip()
            
            # 2. Parse Date
            sent_at = None
            if date_hdr:
                try:
                    sent_at = parsedate_to_datetime(date_hdr)
                except:
                    sent_at = None 
            
            if not sent_at:
                continue # Skip invalid date messages
                
            # 3. Parse Contact (Sender)
            name, email_addr = parseaddr(from_hdr)
            email_addr = email_addr.lower().strip()
            if not email_addr: continue
            
            if email_addr not in buffer_contacts:
                buffer_contacts[email_addr] = name
            else:
                # Update name if longer?
                if len(name) > len(buffer_contacts[email_addr]):
                    buffer_contacts[email_addr] = name
            
            # 4. Extract Body
            body_content = extract_body(message)
            
            # 5. Prepare Payload
            # Prepare metadata
            meta = {}
            if in_reply_to: meta['In-Reply-To'] = in_reply_to
            if references: meta['References'] = references
            
            buffer_messages.append({
                'message_id': msg_id,
                'email': email_addr, # Temporary for lookup
                'subject': subject,
                'content_body': body_content,
                'sent_at': sent_at,
                'metadata_': meta,
                'sender_type': 'user' if 'egawa' in email_addr else 'other' # Very simple heuristic, improve later
            })
            
            count += 1
            if count % BATCH_SIZE == 0:
                flush_buffer(session, buffer_contacts, buffer_messages)
                buffer_contacts = {}
                buffer_messages = []
                print(f"   ... processed {count} messages", end='\r')
                
        except Exception as e:
            # print(f"Error parsing message: {e}")
            continue

    # Final flush
    if buffer_messages:
        flush_buffer(session, buffer_contacts, buffer_messages)
    
    print(f"\n✅ Finished processing {count} messages from {file_path}")

def flush_buffer(session, contacts_dict, messages_list):
    # 1. Upsert Contacts
    if not contacts_dict: return
    
    # Bulk insert/update contacts use Core insert
    # Note: On conflict is specific to dialects
    stmt = insert(Contact).values([
        {'email': e, 'name': n} for e, n in contacts_dict.items()
    ])
    stmt = stmt.on_conflict_do_update(
        index_elements=['email'],
        set_={'name': stmt.excluded.name, 'updated_at': func.now()}
    )
    session.execute(stmt)
    session.commit()
    
    # 2. Get Contact IDs
    emails = list(contacts_dict.keys())
    # Fetch IDs
    rows = session.query(Contact.id, Contact.email).filter(Contact.email.in_(emails)).all()
    email_to_id = {row.email: row.id for row in rows}
    
    # 3. Create dummy Threads (temporary)
    # Strategy: Insert Logic creates a NEW thread for every message initially.
    # Reconstruct script will merge them.
    
    # Insert Threads
    threads_data = []
    for m in messages_list:
        cid = email_to_id.get(m['email'])
        if not cid: continue 
        
        threads_data.append({
            'contact_id': cid,
            'subject': m['subject'],
            'last_message_at': m['sent_at'],
            'message_count': 1,
            'status': 'active'
        })
    
    if not threads_data: return

    stmt_t = insert(Thread).values(threads_data).returning(Thread.id)
    result_t = session.execute(stmt_t).fetchall()
    thread_ids = [r[0] for r in result_t]
    
    # 4. Insert Messages
    msgs_data = []
    for i, m in enumerate(messages_list):
        if i >= len(thread_ids): break 
        
        cid = email_to_id.get(m['email'])
        tid = thread_ids[i]
        
        msgs_data.append({
            'thread_id': tid,
            'contact_id': cid,
            'message_id': m['message_id'],
            'sender_type': m['sender_type'],
            'content_body': m['content_body'],
            'subject': m['subject'],
            'sent_at': m['sent_at'],
            'metadata_': m['metadata_'] # SQLAlchemy JSON handles dict
        })
        
    # Upsert Messages (ignore duplicates)
    stmt_m = insert(Message).values(msgs_data)
    stmt_m = stmt_m.on_conflict_do_nothing(index_elements=['message_id'])
    session.execute(stmt_m)
    session.commit()

def main():
    if len(sys.argv) < 2:
        print("Usage: python import_mbox.py <mbox_path>")
        return
        
    target_path = sys.argv[1]
    
    # Create tables if not exist
    Base.metadata.create_all(bind=engine)
    
    session = Session(bind=engine)
    try:
        # Support wildcard expansion
        import glob
        files = glob.glob(target_path)
        if not files:
            print("No files found.")
            return
            
        for f in files:
            process_mbox(f, session)
            
    finally:
        session.close()

if __name__ == "__main__":
    main()
