import sys
import os
import email
from email.header import decode_header, make_header
from bs4 import BeautifulSoup
from sqlalchemy import text
from app.models import engine, Message

MBOX_FILE = "すべてのメール（迷惑メール、ゴミ箱のメールを含む）-002.mbox"

def normalize_id(mid):
    # Remove <> and whitespace
    return mid.strip().strip('<>').strip()

def get_text_from_html(html_content):
    try:
        soup = BeautifulSoup(html_content, "lxml")
        for script in soup(["script", "style"]):
            script.decompose()
        text = soup.get_text(separator="\n")
        lines = (line.strip() for line in text.splitlines())
        chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
        text = '\n'.join(chunk for chunk in chunks if chunk)
        return text
    except:
        return html_content

def extract_body(msg):
    body = ""
    if msg.is_multipart():
        text_part = None
        html_part = None
        for part in msg.walk():
            ct = part.get_content_type()
            cd = str(part.get("Content-Disposition"))
            if "attachment" in cd: continue
            if ct == "text/plain" and text_part is None: text_part = part
            elif ct == "text/html" and html_part is None: html_part = part
        
        if text_part:
            try: body = text_part.get_payload(decode=True).decode(text_part.get_content_charset() or 'utf-8', errors='replace')
            except: pass
        elif html_part:
            try:
                html = html_part.get_payload(decode=True).decode(html_part.get_content_charset() or 'utf-8', errors='replace')
                body = get_text_from_html(html)
            except: pass
    else:
        try:
            payload = msg.get_payload(decode=True)
            if payload:
                charset = msg.get_content_charset() or 'utf-8'
                body = payload.decode(charset, errors='replace')
                if msg.get_content_type() == "text/html": body = get_text_from_html(body)
        except: pass
    return body.strip().replace('\x00', '')

def run_retry():
    print("🚑 Starting Retry Extraction for missing messages...")
    
    with engine.connect() as conn:
        print("   - Fetching remaining target IDs...")
        stmt = text("""
            SELECT m.message_id 
            FROM messages m
            JOIN threads t ON m.thread_id = t.id
            WHERE t.status = 'active'
            AND m.content_body = 'Pending extraction'
        """)
        rows = conn.execute(stmt).fetchall()
        # Create map of Normalized ID -> Original ID
        target_map = {normalize_id(row[0]): row[0] for row in rows}
        
        print(f"     -> {len(target_map)} messages still pending.")
        if not target_map:
            print("   - No pending messages. All done.")
            return

        print("   - Re-scanning Mbox with normalized matching...")
        
        updates = []
        recovered = 0
        
        with open(MBOX_FILE, 'rb') as f:
            buffer = []
            for line in f:
                if line.startswith(b'From '):
                    if buffer:
                        msg = email.message_from_bytes(b''.join(buffer))
                        raw_mid = msg.get('Message-ID', '').strip()
                        norm_mid = normalize_id(raw_mid)
                        
                        # Check strict match OR normalized match
                        if raw_mid in target_map.values() or norm_mid in target_map:
                            # Recover!
                            # Identify which original ID to update
                            target_id = raw_mid if raw_mid in target_map.values() else target_map[norm_mid]
                            
                            body = extract_body(msg)
                            if body:
                                updates.append({'mid': target_id, 'body': body})
                                recovered += 1
                                # Remove from target to avoid double work? No, map lookup is fast.
                            
                            if len(updates) >= 100:
                                conn.execute(text("UPDATE messages SET content_body = :body WHERE message_id = :mid"), updates)
                                conn.commit()
                                print(f"     ... recovered {recovered} bodies", end='\r')
                                updates = []
                    buffer = []
                buffer.append(line)
            
            if buffer:
                msg = email.message_from_bytes(b''.join(buffer))
                raw_mid = msg.get('Message-ID', '').strip()
                norm_mid = normalize_id(raw_mid)
                if raw_mid in target_map.values() or norm_mid in target_map:
                    target_id = raw_mid if raw_mid in target_map.values() else target_map[norm_mid]
                    body = extract_body(msg)
                    if body:
                         updates.append({'mid': target_id, 'body': body})
                         recovered += 1

            if updates:
                conn.execute(text("UPDATE messages SET content_body = :body WHERE message_id = :mid"), updates)
                conn.commit()
                
        print(f"✅ Retry Complete. Recovered {recovered}/{len(target_map)} messages.")

if __name__ == "__main__":
    run_retry()
