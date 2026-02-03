import sys
import os
import re
import json
from sqlalchemy import text
from app.models import engine

BATCH_SIZE = 100

def extract_financials(text_content):
    if not text_content: return 0, []
    
    amount = 0
    amounts = []
    
    # Normalizing: remove commas
    # Pattern 1: 1,000,000円 or 1000円
    p1 = r'([0-9]{1,3}(,[0-9]{3})*|[0-9]+)\s*円'
    # Pattern 2: ¥1,000,000
    p2 = r'¥\s*([0-9]{1,3}(,[0-9]{3})*|[0-9]+)'
    # Pattern 3: Gold/Man (e.g. 100万円) - Handling Wan/Man units is common in Japan
    p3 = r'([0-9]{1,3}(,[0-9]{3})*|[0-9]+)\s*(万|億)\s*円?'
    
    # Search P1
    for m in re.finditer(p1, text_content):
        try:
            val = int(m.group(1).replace(',', ''))
            amounts.append(val)
        except: pass
        
    # Search P2
    for m in re.finditer(p2, text_content):
        try:
            val = int(m.group(1).replace(',', ''))
            amounts.append(val)
        except: pass
        
    # Search P3 (Units)
    for m in re.finditer(p3, text_content):
        try:
            base = int(m.group(1).replace(',', ''))
            unit = m.group(3)
            if unit == '万': base *= 10000
            elif unit == '億': base *= 100000000
            amounts.append(base)
        except: pass

    if amounts:
        amount = max(amounts)
        
    return amount, list(set(amounts))

def run_feature_extraction():
    print("📊 Starting Feature Extraction (Phase 4)...")
    
    with engine.connect() as conn:
        print("   - Fetching active active threads...")
        
        # Get all active thread IDs
        tids = conn.execute(text("SELECT id FROM threads WHERE status = 'active'")).fetchall()
        tids = [r[0] for r in tids]
        total_threads = len(tids)
        
        # Pre-fetch Blacklisted Contact IDs (Safety net for spam)
        blacklist_keywords = [
            'no-reply', 'noreply', 'donotreply', 'notification', 'bounces', 
            'alert', 'info@', 'support@', 'newsletter', 'mag2', 'magazine', 
            'news@', 'update@', 'press@', 'editor@', 'seminar@'
        ]
        blacklist_ids = set()
        for kw in blacklist_keywords:
            ids = conn.execute(text(f"SELECT id FROM contacts WHERE LOWER(email) LIKE '%{kw}%'")).fetchall()
            for r in ids:
                blacklist_ids.add(r[0])
        
        print(f"     -> Loaded {len(blacklist_ids)} blacklisted contacts for scoring safety.")
        print(f"     -> Analyzing {total_threads} threads...")
        
        processed = 0
        
        for i in range(0, total_threads, BATCH_SIZE):
            batch_tids = tids[i : i + BATCH_SIZE]
            if not batch_tids: break
            
            # Fetch messages for this batch of threads
            # Manually format IN clause for SQLite stability
            tids_str = ",".join(str(tid) for tid in batch_tids)
            stmt_msgs = text(f"""
                SELECT thread_id, content_body, sent_at, contact_id
                FROM messages
                WHERE thread_id IN ({tids_str})
                ORDER BY sent_at ASC
            """)
            msgs = conn.execute(stmt_msgs).fetchall()
            
            # Group by thread
            thread_data = {tid: [] for tid in batch_tids}
            for m in msgs:
                if m[0] in thread_data:
                    thread_data[m[0]].append(m)
            
            updates = []
            
            import math
            import datetime

            for tid in batch_tids:
                messages = thread_data[tid]
                
                # 1. Financial Value Scan
                max_val = 0
                found_list = []
                for msg in messages:
                    # msg[1] is content_body
                    if msg[1]:
                         val, vals = extract_financials(str(msg[1]))
                         if val > max_val: max_val = val
                         found_list.extend(vals)
                
                found_list = sorted(list(set(found_list)), reverse=True)
                
                # 2. Interactivity (Unique Senders)
                senders = set(m[3] for m in messages if m[3] is not None) # msg[3] is contact_id
                unique_senders = len(senders)
                
                # 3. Density (Average Time Gap)
                density_bonus = 1.0
                if len(messages) > 1:
                    timestamps = [m[2] for m in messages if m[2]]
                    if len(timestamps) > 1:
                        # Ensure timestamps are datetime
                        if isinstance(timestamps[0], str):
                            # Simplistic parse if string
                            pass 
                        else:
                            total_gap = (timestamps[-1] - timestamps[0]).total_seconds()
                            avg_gap = total_gap / (len(timestamps) - 1)
                            
                            # High Density: < 1 hour avg gap -> x1.5
                            if avg_gap < 3600: density_bonus = 1.5
                            # Medium: < 1 day -> x1.2
                            elif avg_gap < 86400: density_bonus = 1.2
                            # Low: > 1 week -> x0.8
                            elif avg_gap > 604800: density_bonus = 0.8
                
                # --- SCORING FORMULA ---
                # A. Base Volume (Capped / Log-scaled for spam prevention)
                msg_count = len(messages)
                if msg_count <= 20:
                    base_score = float(msg_count)
                else:
                    # Logarithmic growth after 20 messages to prevent spam domination
                    # 20 -> 20, 100 -> 20 + log(80)*2 ~= 26, 1000 -> 32
                    base_score = 20.0 + math.log(msg_count - 19) * 2.0
                
                # B. Financial Impact (Log Scale)
                # 10,000yen -> log10=4 -> 8 pts
                # 1,000,000yen -> log10=6 -> 12 pts
                financial_score = 0
                if max_val > 0:
                    financial_score = math.log10(max_val) * 2.0
                
                # C. Interactivity Multiplier
                # One-way (1 sender) = 1.0 (No bonus, maybe penalty?)
                # Two-way (2+ senders) = 1.5 (Strong indicator of human conversation)
                interact_mult = 1.5 if unique_senders >= 2 else 1.0
                
                if unique_senders == 1 and msg_count > 5:
                     # Penalize long monologue (e.g. newsletters/DM) severely
                     interact_mult = 0.1

                final_score = (base_score + financial_score) * density_bonus * interact_mult
                
                # Hard cap for one-way threads (never exceed 10.0)
                if unique_senders == 1 and final_score > 10.0:
                    final_score = 10.0
                
                # --- SAFETY NET: Force 0 for blacklisted contacts ---
                # Determine thread owner (approximate from first message sender or any message)
                # Ideally we should fetch thread.contact_id, but checking all message senders works too.
                # If ALL senders are in blacklist, kill it.
                is_spam = False
                if messages:
                    # Check the primary contact (usually the first sender if it's incoming)
                    first_sender = messages[0][3]
                    if first_sender in blacklist_ids:
                        is_spam = True
                        final_score = 0.0
                
                meta = {
                    "estimated_value": max_val,
                    "all_values": found_list[:5],
                    "message_qty": len(messages),
                    "unique_senders": unique_senders,
                    "density_bonus": density_bonus
                }
                
                updates.append({
                    "tid": tid,
                    "score": round(final_score, 2),
                    "meta": json.dumps(meta)
                })
            
            # Batch update
            stmt_update = text("""
                UPDATE threads 
                SET score = :score, metadata_ = :meta
                WHERE id = :tid
            """)
            conn.execute(stmt_update, updates)
            conn.commit()
            
            processed += len(batch_tids)
            print(f"     ... analyzed {processed}/{total_threads} threads", end='\r')
            
    print(f"\n✅ Feature Extraction Complete. Processed {processed} threads.")

    # Skip Expanding Score Columns (SQLite does not support ALTER COLUMN TYPE)
    print("   - Skipping column expansion (SQLite).")

    print("   - Aggregating Contact Scores...")
    with engine.connect() as conn:
        # 1. Reset all scores to 0 first (Critical! Otherwise contacts with all-ignored threads retain old scores)
        conn.execute(text("UPDATE contacts SET closeness_score = 0"))
        
        # 2. Update with new sums
        # SQLite compatible UPDATE with correlated subquery
        stmt_agg = text("""
            UPDATE contacts
            SET closeness_score = (
                SELECT IFNULL(SUM(score), 0) FROM threads WHERE contacts.id = threads.contact_id AND status = 'active'
            ),
            last_contacted_at = (
                SELECT MAX(last_message_at) FROM threads WHERE contacts.id = threads.contact_id AND status = 'active'
            )
            WHERE id IN (SELECT contact_id FROM threads WHERE status = 'active')
        """)
        conn.execute(stmt_agg)
        conn.commit()
    print("✅ Contact Scores Updated.")

if __name__ == "__main__":
    run_feature_extraction()
