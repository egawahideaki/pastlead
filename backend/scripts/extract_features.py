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
        
        print(f"     -> Analyzing {total_threads} threads...")
        
        processed = 0
        
        for i in range(0, total_threads, BATCH_SIZE):
            batch_tids = tids[i : i + BATCH_SIZE]
            if not batch_tids: break
            
            # Fetch messages for this batch of threads
            # Using IN clause
            stmt_msgs = text("""
                SELECT thread_id, content_body, sender_type
                FROM messages
                WHERE thread_id = ANY(:tids)
            """)
            msgs = conn.execute(stmt_msgs, {"tids": batch_tids}).fetchall()
            
            # Group by thread
            thread_data = {tid: [] for tid in batch_tids}
            for m in msgs:
                if m[0] in thread_data:
                    thread_data[m[0]].append(m)
            
            updates = []
            
            for tid in batch_tids:
                messages = thread_data[tid]
                
                max_val = 0
                found_list = []
                
                for msg in messages:
                    # msg[1] is content_body
                    if msg[1]:
                         val, vals = extract_financials(str(msg[1]))
                         if val > max_val: max_val = val
                         found_list.extend(vals)
                
                # Dedupe found_list
                found_list = sorted(list(set(found_list)), reverse=True)
                
                # Heuristic Score
                # Base score = 0
                # +1 per message (density)
                # + Log(Value) ? Or just linear for now? 
                # Let's do: Log10(Value + 1) * 10 + MsgCount
                import math
                val_score = 0
                if max_val > 0:
                    val_score = math.log10(max_val) * 10
                
                final_score = val_score + len(messages)
                
                meta = {
                    "estimated_value": max_val,
                    "all_values": found_list[:5], # Top 5
                    "message_qty": len(messages)
                }
                
                updates.append({
                    "tid": tid,
                    "score": round(final_score, 2),
                    "meta": json.dumps(meta)
                })
            
            # Batch update
            stmt_update = text("""
                UPDATE threads 
                SET score = :score, metadata_ = CAST(:meta AS jsonb) 
                WHERE id = :tid
            """)
            conn.execute(stmt_update, updates)
            conn.commit()
            
            processed += len(batch_tids)
            print(f"     ... analyzed {processed}/{total_threads} threads", end='\r')
            
    print(f"\n✅ Feature Extraction Complete. Processed {processed} threads.")

if __name__ == "__main__":
    run_feature_extraction()
