import re
import networkx as nx
from sqlalchemy import text
from app.models import engine

def normalize_msg_id(mid):
    if not mid: return None
    clean = mid.strip().strip('<>')
    # Strict Validation: Must contain '@' and be at least 5 chars
    if '@' not in clean or len(clean) < 5:
        return None
    return clean

def normalize_subject(subject):
    if not subject: return ""
    # Remove Re:, Fwd: etc. and cleanup whitespace
    s = re.sub(r'[\r\n\t]', ' ', subject)
    s = re.sub(r'([\[\(].*?[\]\)])', '', s) # Remove [...]
    s = re.sub(r'^(re|fwd|fw|aw|antw|回复|回覆|転送|返信)[:：]\s*', '', s, flags=re.IGNORECASE).strip()
    return s.strip()

def reconstruct_threads_strict_v2():
    print("🧵 Starting STRICT V2 Thread Reconstruction...")
    print("   (Policy: Valid Message-ID + Consistent Subject ONLY)")
    
    with engine.connect() as conn:
        print("   - Fetching Messages...")
        # We need subject now. We recovered it in previous step.
        stmt = text("""
            SELECT id, message_id, 
                   metadata_->>'In-Reply-To', metadata_->>'References', 
                   contact_id, sent_at, subject
            FROM messages
        """)
        rows = conn.execute(stmt).fetchall()
        print(f"     -> Loaded {len(rows)} messages.")
        
        G = nx.Graph()
        mid_to_pk = {}
        pk_to_data = {}
        
        # 1. Build Nodes
        for row in rows:
            pk = row[0]
            raw_mid = row[1]
            subject = row[6] or "" # Subject might be null if recovery missed some
            
            mid = normalize_msg_id(raw_mid)
            if not mid:
                mid = f"pk:{pk}" # Isolation fallback
            
            norm_subj = normalize_subject(subject)
            
            G.add_node(mid, subject=norm_subj)
            mid_to_pk[mid] = pk
            pk_to_data[pk] = {'mid': mid, 'subject': subject, 'norm_subj': norm_subj, 'cid': row[4]}
            
        print(f"     -> Nodes verified.")
        
        # 2. Build Edges (With SUBJECT Guard)
        edge_count = 0
        skipped_count = 0
        
        for row in rows:
            pk = row[0]
            raw_mid = row[1]
            in_reply_to = row[2]
            references = row[3]
            
            my_mid = pk_to_data[pk]['mid']
            my_subj = pk_to_data[pk]['norm_subj']
            
            # Collect potential parents
            refs = []
            if in_reply_to: refs.append(in_reply_to)
            # We treat References as a chain, but here we just link to all predecessors?
            # Standard is: last ref is parent.
            # But let's verify all.
            if references: refs.extend(references.split())
            
            for r in refs:
                target_mid = normalize_msg_id(r)
                if not target_mid: continue
                
                # Check if target exists in our graph (we only link to KNOWN messages to check subject)
                # If target is unknown (external/missing), we can't check subject.
                # Gmail Policy: If we don't know the parent, we assume it belongs to this thread 
                # UNLESS we have a better cluster.
                # But here, we want to avoid mixing.
                # If target is IN our DB, we check subject.
                # If target is NOT in our DB, we add edge comfortably? 
                # No, if target is NOT in DB, it might be the 'Hub' that causes mixing!
                # Wait, if target is NOT in DB, it's just a string node in Graph.
                # If 'Meeting A' replies to 'Hub X', and 'Meeting B' replies to 'Hub X',
                # and 'Hub X' is missing from DB. They get linked via Hub X.
                # THIS IS THE DANGER.
                
                if target_mid in mid_to_pk:
                    # Target is in DB. Check Subject Compatibility.
                    target_pk = mid_to_pk[target_mid]
                    target_subj = pk_to_data[target_pk]['norm_subj']
                    
                    # Fuzzy match or Exact?
                    # Let's use Exact for now to be safe.
                    if my_subj == target_subj or prev_subj_match(my_subj, target_subj):
                        G.add_edge(my_mid, target_mid)
                        edge_count += 1
                    else:
                        # Subject Mismatch -> CUT
                        skipped_count += 1
                else:
                    # Target is NOT in DB.
                    # We have no Subject info for Target.
                    # DANGER: If we link to this ghost, we might merge distinct threads.
                    # SAFE Strategy: DO NOT link to ghosts. 
                    # Only link to messages we actually hold.
                    # This fragments threads where intermediate messages are missing... but it's safer.
                    # Or: Link only if 'In-Reply-To' (immediate parent).
                    # References list often contains the very first email (Root). 
                    # If everyone includes Root ID, and Root is missing, everyone links to Root Ghost.
                    # Combining this with Subject check is hard on Ghost.
                    
                    # DECISION: Ignore Ghosts. 
                    # If we don't have the message, we don't link.
                    # This ensures we only link based on VERIFIED content.
                    # (Users might see fragmented threads if they deleted the middle email, but better than mixing)
                    pass
                    
        print(f"     -> Edges built: {edge_count} (Skipped {skipped_count} due to subject mismatch/ghosts).")
        
        # 3. Component Extraction & DB Update
        components = list(nx.connected_components(G))
        print(f"     -> Found {len(components)} clean threads.")
        
        # ... (Same DB Update Logic as Force Reset) ...
        # Reuse logic: Create new threads for all.
        
        # Prepare Data
        valid_components = []
        for comp in components:
            db_pks = []
            for node in comp:
                if node in mid_to_pk:
                    db_pks.append(mid_to_pk[node])
            if db_pks:
                valid_components.append(db_pks)

        # Insert Threads
        print("   - Creating Tables...")
        inserts = []
        comp_map = {}
        
        # Need to sort by date
        # Cache sent_at
        
        for i, pks in enumerate(valid_components):
            # Sort PKs by sent_at
            pks.sort(key=lambda pk: pk_to_data[pk].get('sent_at') or str(pk))
            leader = pks[0]
            data = pk_to_data[leader]
            
            inserts.append({
                'subject': data['subject'],
                'contact_id': data['cid'],
                'status': 'active'
            })
            comp_map[i] = pks
            
        print(f"     -> Inserting {len(inserts)} threads...")
        
        # Bulk Insert
        created_ids = []
        stmt_ins = text("INSERT INTO threads (subject, contact_id, status, created_at) VALUES (:subject, :contact_id, :status, NOW()) RETURNING id")
        
        for i, item in enumerate(inserts):
            res = conn.execute(stmt_ins, item).scalar()
            created_ids.append(res)
            if i % 1000 == 0:
                 print(f"       .. {i}", end='\r')
        print(f"       .. Done")
        
        # Assign
        print("   - Linking...")
        updates = []
        for i, tid in enumerate(created_ids):
             for pk in comp_map[i]:
                 updates.append({'pk': pk, 'tid': tid})
                 
        # Batch Update
        batch_size = 5000
        stmt_upd = text("UPDATE messages SET thread_id = :tid WHERE id = :pk")
        for i in range(0, len(updates), batch_size):
            conn.execute(stmt_upd, updates[i:i+batch_size])
            print(f"       .. {i}", end='\r')
            
        conn.commit()
        
        # Cleanup
        conn.execute(text("DELETE FROM threads WHERE id NOT IN (SELECT DISTINCT thread_id FROM messages)"))
        
        # Stats
        conn.execute(text("""
            UPDATE threads
            SET message_count = sub.cnt,
                last_message_at = sub.last_at
            FROM (
                SELECT thread_id, count(*) as cnt, max(sent_at) as last_at
                FROM messages
                GROUP BY thread_id
            ) sub
            WHERE threads.id = sub.thread_id
        """))
        conn.commit()

    print("✅ Strict V2 Complete.")

def prev_subj_match(s1, s2):
    # Allow minor variations?
    # For now, strict equality on normalized string is best.
    return s1 == s2

if __name__ == "__main__":
    reconstruct_threads_strict_v2()
