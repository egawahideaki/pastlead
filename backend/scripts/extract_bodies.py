import sys
import os
import email
from email.header import decode_header, make_header
from bs4 import BeautifulSoup
from sqlalchemy import text
from app.models import engine, Message
import time

MBOX_FILE = "すべてのメール（迷惑メール、ゴミ箱のメールを含む）-002.mbox"
BATCH_SIZE = 500

def get_text_from_html(html_content):
    try:
        soup = BeautifulSoup(html_content, "lxml")
        # Remove script and style elements
        for script in soup(["script", "style"]):
            script.decompose()
        text = soup.get_text(separator="\n")
        # Break into lines and remove leading and trailing space on each
        lines = (line.strip() for line in text.splitlines())
        # Break multi-headlines into a line each
        chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
        # Drop blank lines
        text = '\n'.join(chunk for chunk in chunks if chunk)
        return text
    except:
        return html_content

def decode_mime_words(s):
    if not s: return ""
    try:
        return str(make_header(decode_header(s)))
    except:
        return s

def extract_body(msg):
    body = ""
    if msg.is_multipart():
        # Iterate parts, prefer text/plain, then text/html
        text_part = None
        html_part = None
        for part in msg.walk():
            content_type = part.get_content_type()
            content_disposition = str(part.get("Content-Disposition"))
            
            if "attachment" in content_disposition:
                continue
                
            if content_type == "text/plain" and text_part is None:
                text_part = part
            elif content_type == "text/html" and html_part is None:
                html_part = part
        
        if text_part:
            try:
                body = text_part.get_payload(decode=True).decode(text_part.get_content_charset() or 'utf-8', errors='replace')
            except:
                pass
        elif html_part:
            try:
                html = html_part.get_payload(decode=True).decode(html_part.get_content_charset() or 'utf-8', errors='replace')
                body = get_text_from_html(html)
            except:
                pass
    else:
        # Single part
        try:
            payload = msg.get_payload(decode=True)
            if payload:
                charset = msg.get_content_charset() or 'utf-8'
                body = payload.decode(charset, errors='replace')
                if msg.get_content_type() == "text/html":
                    body = get_text_from_html(body)
        except:
            pass
            
    # Sanitize NUL characters which PostgreSQL cannot handle
    return body.strip().replace('\x00', '')

def run_extraction():
    print("📖 Starting Content Extraction (Phase 2)...")
    
    with engine.connect() as conn:
        print("   - Fetching target message IDs (Active Threads only)...")
        # Get message_ids for ACTIVE threads where body is 'Pending extraction'
        # Also select ID (primary key) for faster update
        stmt = text("""
            SELECT m.message_id 
            FROM messages m
            JOIN threads t ON m.thread_id = t.id
            WHERE t.status = 'active'
            AND m.content_body = 'Pending extraction'
        """)
        result = conn.execute(stmt).fetchall()
        target_ids = set(row[0] for row in result) # Set of Message-IDs (string)
        
        print(f"     -> Found {len(target_ids)} messages to extract.")
        
        if not target_ids:
            print("   - No pending messages found.")
            return

        print("   - Scanning Mbox file...")
        
        if not os.path.exists(MBOX_FILE):
             print(f"❌ Error: {MBOX_FILE} not found.")
             return

        updates = []
        extracted_count = 0
        
        # Open Mbox in binary mode for speed
        with open(MBOX_FILE, 'rb') as f:
            buffer = []
            for line in f:
                if line.startswith(b'From '):
                    if buffer:
                        # Process previous buffer
                        msg_bytes = b''.join(buffer)
                        # Quick check if Message-ID is in target (need to parse header first?)
                        # Parsing full message is slow. We can try to grep Message-ID from bytes?
                        # But Message-ID header location varies.
                        # Let's parse header only first? Python's email policy=HTTP or default.
                        
                        # Optimization: Check if this message is in our target list
                        # Convert buffer to string is costly.
                        # We parse message object.
                        msg = email.message_from_bytes(msg_bytes)
                        mid = msg.get('Message-ID', '').strip()
                        
                        if mid in target_ids:
                            # Extract Body
                            body = extract_body(msg)
                            if body:
                                updates.append({'mid': mid, 'body': body})
                                extracted_count += 1
                                target_ids.remove(mid) # Remove from set to speed up lookup? No, checking set is O(1).
                                # Actually we can stop if target_ids is empty, but order is random.
                            
                            if len(updates) >= BATCH_SIZE:
                                # Batch Update
                                conn.execute(
                                    text("UPDATE messages SET content_body = :body WHERE message_id = :mid"),
                                    updates
                                )
                                conn.commit()
                                print(f"     ... updated {extracted_count} bodies", end='\r')
                                updates = []

                    buffer = []
                buffer.append(line)
            
            # Last message
            if buffer:
                msg = email.message_from_bytes(b''.join(buffer))
                mid = msg.get('Message-ID', '').strip()
                if mid in target_ids:
                    body = extract_body(msg)
                    if body:
                        updates.append({'mid': mid, 'body': body})
                        extracted_count += 1
                        
            # Final batch
            if updates:
                conn.execute(
                    text("UPDATE messages SET content_body = :body WHERE message_id = :mid"),
                    updates
                )
                conn.commit()
                print(f"     ... updated {extracted_count} bodies")
                
        print(f"✅ Extraction Complete. Updated {extracted_count} messages.")

if __name__ == "__main__":
    run_extraction()
