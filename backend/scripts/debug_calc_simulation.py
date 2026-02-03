from app.models import engine
from sqlalchemy import text
import math
import json

def extract_financials(text_content):
    if not text_content: return 0, []
    amount = 0
    amounts = []
    p1 = r'([0-9]{1,3}(,[0-9]{3})*|[0-9]+)\s*円'
    p2 = r'¥\s*([0-9]{1,3}(,[0-9]{3})*|[0-9]+)'
    p3 = r'([0-9]{1,3}(,[0-9]{3})*|[0-9]+)\s*(万|億)\s*円?'
    import re
    for m in re.finditer(p1, text_content):
        try:
            val = int(m.group(1).replace(',', ''))
            amounts.append(val)
        except: pass
    for m in re.finditer(p2, text_content):
        try:
            val = int(m.group(1).replace(',', ''))
            amounts.append(val)
        except: pass
    for m in re.finditer(p3, text_content):
        try:
            base = int(m.group(1).replace(',', ''))
            unit = m.group(3)
            if unit == '万': base *= 10000
            elif unit == '億': base *= 100000000
            amounts.append(base)
        except: pass
    if amounts: amount = max(amounts)
    return amount, list(set(amounts))

def simulate_scoring():
    print("🔬 Simulating Scoring Logic for Top Contact threads...")
    
    with engine.connect() as conn:
        stmt = text("SELECT id, name, email, closeness_score FROM contacts WHERE closeness_score > 20 LIMIT 1")
        contact = conn.execute(stmt).fetchone()
        
        if not contact:
            print("❌ No high score contact found. Maybe DB is clean?")
            # Try to find 'itmedia' specifically just in case
            stmt = text("SELECT id, name, email, closeness_score FROM contacts WHERE email LIKE '%itmedia%' LIMIT 1")
            contact = conn.execute(stmt).fetchone()
            if not contact:
                print("❌ Even ITmedia is gone/clean.")
                return

        cid, name, email, score = contact
        print(f"🎯 Target: {name} <{email}> (DB Score: {score})")
        
        # Get active threads
        stmt_threads = text(f"SELECT id FROM threads WHERE contact_id = {cid} AND status = 'active' LIMIT 5")
        tids = conn.execute(stmt_threads).fetchall()
        
        for r in tids:
            tid = r[0]
            print(f"   \n🧵 Thread [{tid}]:")
            
            # Fetch messages
            stmt_msgs = text(f"SELECT content_body, sent_at, contact_id FROM messages WHERE thread_id = {tid} ORDER BY sent_at ASC")
            msgs = conn.execute(stmt_msgs).fetchall()
            messages = [(None, m[0], m[1], m[2]) for m in msgs] # Match extract_features format roughly
            
            # --- LOGIC COPY START ---
            max_val = 0
            found_list = []
            for msg in messages:
                if msg[1]: 
                     val, vals = extract_financials(str(msg[1]))
                     if val > max_val: max_val = val
                     found_list.extend(vals)
            
            msg_count = len(messages)
            senders = set(m[3] for m in messages if m[3] is not None)
            unique_senders = len(senders)
            
            print(f"     - Msgs: {msg_count}, Unique Senders: {unique_senders}")
            print(f"     - Senders Set: {senders}")
            print(f"     - Max Financial: {max_val}")

            final_score = 0.0
            
            if unique_senders >= 2:
                print("     - Mode: CONVERSATION")
                if msg_count > 20:
                    vol_score = 20.0 + math.log(msg_count - 19) * 2.0
                else:
                    vol_score = float(msg_count) * 1.2
                
                fin_score = math.log10(max_val) * 3.0 if max_val > 0 else 0
                final_score = vol_score + fin_score
                
                if len(messages) > 1:
                     # density simplified
                     if (messages[-1][2] - messages[0][2]).total_seconds() / (len(messages)-1) < 86400:
                         final_score *= 1.1
            else:
                print("     - Mode: MONOLOGUE")
                final_score = 0.5
                if max_val > 0: final_score += 0.5
                if final_score > 1.0: final_score = 1.0
                
                if messages:
                    last_body = (messages[-1][1] or "").lower()
                    spam_triggers = ["unsubscribe", "配信停止", "送信専用", "解除", "opt-out", "donotreply", "no-reply"]
                    if any(k in last_body for k in spam_triggers):
                        print("     - HIT Spam Keyword!")
                        final_score = 0.0

            print(f"     => CALCULATED SCORE: {final_score}")
            # --- LOGIC COPY END ---

if __name__ == "__main__":
    simulate_scoring()
