import sys
import os
import re
import json
import email
from email.header import decode_header, make_header
from email.utils import parseaddr, parsedate_to_datetime
from bs4 import BeautifulSoup
import unicodedata

# Add parent directory to path to allow importing app.models
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.models import engine, Base, Contact, Thread, Message, create_tables
from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy import text, func

BATCH_SIZE = 2000 # Increased batch size for speed

# --- Helper Functions ---

def resolve_path(path_str):
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
    if not text_body: return ""
    lines = text_body.split('\n')
    cleaned_lines = []
    quote_headers = [
        re.compile(r'^On\s.*wrote:', re.IGNORECASE),
        re.compile(r'^---+\s*Original Message\s*---+', re.IGNORECASE),
        re.compile(r'^From:\s', re.IGNORECASE),
        re.compile(r'^Sent from my', re.IGNORECASE)
    ]
    for line in lines:
        sline = line.strip()
        if sline.startswith('>'): continue
        is_quote = False
        for qh in quote_headers:
            if qh.match(sline):
                if sline.lower().startswith("on ") and sline.endswith("wrote:"):
                     return "\n".join(cleaned_lines).strip()
                if "original message" in sline.lower():
                     return "\n".join(cleaned_lines).strip()
                if "sent from my" in sline.lower():
                    return "\n".join(cleaned_lines).strip()
        cleaned_lines.append(line)
    return "\n".join(cleaned_lines).strip()

def extract_body(message):
    body_text = ""
    if message.is_multipart():
        for part in message.walk():
            if part.get_content_maintype() == 'text':
                payload = part.get_payload(decode=True)
                if not payload: continue
                charset = part.get_content_charset() or 'utf-8'
                try: text_chunk = payload.decode(charset, errors='ignore')
                except: text_chunk = payload.decode('utf-8', errors='ignore')
                subtype = part.get_content_subtype()
                if subtype == 'plain':
                    body_text = text_chunk
                    break
                elif subtype == 'html':
                    if not body_text:
                        soup = BeautifulSoup(text_chunk, 'lxml')
                        body_text = soup.get_text('\n')
    else:
        payload = message.get_payload(decode=True)
        if payload:
            charset = message.get_content_charset() or 'utf-8'
            try: body_text = payload.decode(charset, errors='ignore')
            except: body_text = payload.decode('utf-8', errors='ignore')
            if message.get_content_subtype() == 'html':
                soup = BeautifulSoup(body_text, 'lxml')
                body_text = soup.get_text('\n')
    return clean_quote(body_text)

def process_single_message(msg_bytes, session, buffer_contacts, buffer_messages, existing_mids):
    try:
        message = email.message_from_bytes(msg_bytes)
        
        msg_id = message.get('Message-ID', '').strip()
        
        # Clean ID
        if msg_id.startswith('<') and msg_id.endswith('>'):
            clean_id = msg_id[1:-1]
        else:
            clean_id = msg_id
            
        if not clean_id: return False # Skip no ID
        
        # Resume Logic (Skip existing)
        if clean_id in existing_mids:
            return False

        subject = decode_mime_header(message.get('Subject', ''))
        from_hdr = decode_mime_header(message.get('From', ''))
        date_hdr = message.get('Date', '')
        
        sent_at = None
        if date_hdr:
            try: sent_at = parsedate_to_datetime(date_hdr)
            except: sent_at = None
        if not sent_at: return False

        name, email_addr = parseaddr(from_hdr)
        email_addr = email_addr.lower().strip()
        if not email_addr: return False
        
        # Buffer Contact
        if email_addr not in buffer_contacts:
            buffer_contacts[email_addr] = name
        else:
            if len(name) > len(buffer_contacts[email_addr]):
                buffer_contacts[email_addr] = name
        
        # Buffer Message
        body_content = extract_body(message)
        
        meta = {}
        if message.get('In-Reply-To'): meta['In-Reply-To'] = message.get('In-Reply-To').strip()
        if message.get('References'): meta['References'] = message.get('References').strip()
        
        # Check sender (Owner determination)
        # We can try to guess from the From address or use env var.
        # For now simple check:
        # sender_type = 'user' if 'my_email' in email_addr else 'other' 
        # (Ideally passed via Env or Arg, but let's default to 'other' and fix later or use specific logic)
        
        buffer_messages.append({
            'message_id': clean_id,
            'email': email_addr,
            'subject': subject,
            'content_body': body_content,
            'sent_at': sent_at,
            'metadata_': meta,
            'sender_type': 'other' # Needs update logic
        })
        return True
    except Exception:
        return False

def flush_buffer(session, contacts_dict, messages_list):
    if not contacts_dict: return
    
    # Upsert Contacts
    stmt = insert(Contact).values([{'email': e, 'name': n} for e, n in contacts_dict.items()])
    stmt = stmt.on_conflict_do_update(index_elements=['email'], set_={'name': stmt.excluded.name, 'updated_at': func.now()})
    session.execute(stmt)
    session.commit()
    
    # Get IDs
    emails = list(contacts_dict.keys())
    rows = session.query(Contact.id, Contact.email).filter(Contact.email.in_(emails)).all()
    email_to_id = {row.email: row.id for row in rows}
    
    # Insert Threads
    threads_data = []
    valid_msgs = []
    
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
        valid_msgs.append(m)
    
    if not threads_data: return

    stmt_t = insert(Thread).values(threads_data).returning(Thread.id)
    result_t = session.execute(stmt_t).fetchall()
    thread_ids = [r[0] for r in result_t]
    
    # Insert Messages
    msgs_data = []
    for i, m in enumerate(valid_msgs):
        msgs_data.append({
            'thread_id': thread_ids[i],
            'contact_id': email_to_id.get(m['email']),
            'message_id': m['message_id'],
            'sender_type': m['sender_type'],
            'content_body': m['content_body'],
            'subject': m['subject'],
            'sent_at': m['sent_at'],
            'metadata_': json.dumps(m['metadata_'])
        })
        
    stmt_m = insert(Message).values(msgs_data)
    stmt_m = stmt_m.on_conflict_do_nothing(index_elements=['message_id'])
    session.execute(stmt_m)
    session.commit()

def process_mbox_streaming(file_path, session):
    file_size = os.path.getsize(file_path)
    print(f"🚀 Streaming High-Speed Parse: {file_path} (Size: {file_size / (1024*1024):.1f} MB)")
    
    # Load Existing IDs (Resume Support)
    existing_mids = set()
    try:
        with engine.connect() as conn:
            result = conn.execute(text("SELECT message_id FROM messages"))
            for r in result: existing_mids.add(r[0])
        print(f"   ⏩ Skipping {len(existing_mids)} existing messages.")
    except: pass

    buffer_contacts = {}
    buffer_messages = []
    count = 0
    skipped = 0
    
    # Streaming Logic
    current_lines = []
    in_message = False
    
    with open(file_path, 'rb') as f:
        for line in f:
            if line.startswith(b'From '):
                # End of previous message
                if in_message and current_lines:
                    msg_bytes = b''.join(current_lines)
                    is_new = process_single_message(msg_bytes, session, buffer_contacts, buffer_messages, existing_mids)
                    if is_new:
                        count += 1
                    else:
                        skipped += 1
                        
                    if len(buffer_messages) >= BATCH_SIZE:
                        flush_buffer(session, buffer_contacts, buffer_messages)
                        buffer_contacts = {}
                        buffer_messages = []
                        
                        # Progress status
                        current_pos = f.tell()
                        progress_pct = (current_pos / file_size) * 100
                        print(f"   ... {progress_pct:.1f}% done | {count} msgs (skipped {skipped})", end='\r')
                        
                # Start new message
                current_lines = [line]
                in_message = True
            else:
                if in_message:
                    current_lines.append(line)
                    
        # Flush last message
        if in_message and current_lines:
            msg_bytes = b''.join(current_lines)
            if process_single_message(msg_bytes, session, buffer_contacts, buffer_messages, existing_mids):
                count += 1
            else:
                skipped += 1

    # Final Buffer Flush
    if buffer_messages:
        flush_buffer(session, buffer_contacts, buffer_messages)

    print(f"\n✅ Done! Processed: {count}, Skipped: {skipped}")

def main():
    if len(sys.argv) < 2: return
    target_path = sys.argv[1]
    create_tables()
    session = Session(bind=engine)
    try:
        import glob
        files = glob.glob(target_path)
        for f in files:
            process_mbox_streaming(f, session)
    finally:
        session.close()

if __name__ == "__main__":
    main()
