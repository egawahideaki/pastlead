import re
import networkx as nx
from sqlalchemy import text
from app.models import engine
import time

def normalize_msg_id(mid):
    if not mid: return None
    # Remove < and >, and whitespace
    return mid.strip().strip('<>')

def force_reset_threads():
    print("🧨 Starting FORCE RESET of Threads...")
    
    with engine.connect() as conn:
        print("   - Fetching Message Headers...")
        
        # Load all messages needed for graph
        # We need headers to build graph.
        # We also need 'message_id' (our internal column), 'id' (PK), 'subject', 'sent_at', 'contact_id'
        # 'metadata_' contains the raw headers.
        
        stmt = text("""
            SELECT id, message_id, 
                   metadata_->>'In-Reply-To', metadata_->>'References', 
                   contact_id, sent_at
            FROM messages
        """)
        
        # NOTE: Subject is tricky. If we delete all threads, we lose the subject info if it's only stored on Thread.
        # import_mbox_fast stores subject in Thread. 
        # Does Message table have subject? No.
        # Check models.py
        # Thread has subject. Message has content_body.
        # If we delete threads, we lose "Subject" text for messages!
        # WE MUST PRESERVE SUBJECTS.
        
        # Strategy:
        # 1. Fetch Subject from current Threads before deleting them.
        #    Map MessageID -> CurrentThread -> Subject.
        
        print("   - Preserving Subjects...")
        stmt_subjects = text("""
            SELECT m.id, t.subject
            FROM messages m
            JOIN threads t ON m.thread_id = t.id
        """)
        rows_subj = conn.execute(stmt_subjects).fetchall()
        
        pk_to_subject = {}
        for r in rows_subj:
            pk_to_subject[r[0]] = r[1]
            
        print(f"     -> Preserved subjects for {len(pk_to_subject)} messages.")
        
        # Now fetch headers
        print("   - Loading Headers...")
        rows = conn.execute(stmt).fetchall()
        print(f"     -> Loaded {len(rows)} messages.")
        
        # Build Graph
        G = nx.Graph()
        
        pk_to_data = {} # pk -> {mid, contact_id, sent_at, subject}
        mid_to_pk = {}  # mid_str -> pk (for existing messages)
        
        for row in rows:
            pk = row[0]
            raw_mid = row[1]
            in_reply_to = row[2]
            references = row[3]
            contact_id = row[4]
            sent_at = row[5]
            
            subject = pk_to_subject.get(pk, "(No Subject)")
            
            mid = normalize_msg_id(raw_mid)
            if not mid:
                # If no Message-ID, use unique dummy
                mid = f"pk:{pk}"
            
            G.add_node(mid)
            mid_to_pk[mid] = pk
            pk_to_data[pk] = {
                'mid': mid, 
                'contact_id': contact_id, 
                'sent_at': sent_at,
                'subject': subject
            }
            
            # Edges
            if mid.startswith("pk:"): continue
            
            refs = []
            if in_reply_to: refs.append(in_reply_to)
            if references: refs.extend(references.split())
            
            for r in refs:
                ref = normalize_msg_id(r)
                if ref:
                    G.add_edge(mid, ref)
            
        print(f"     -> Graph built: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges.")
        
        # Connected Components
        print("   - Identifying Components...")
        components = list(nx.connected_components(G))
        print(f"     -> Found {len(components)} strict components.")
        
        # Prepare for Rewrite
        print("   - 🗑️  Truncating Threads table (Cascading to Messages? No, we need messages!)")
        # We cannot truncate threads because messages.thread_id is FK.
        # We must set messages.thread_id to NULL first? 
        # But column might be NOT NULL.
        # Check models.py -> thread_id is nullable=False.
        
        # WORKAROUND: We create NEW threads first based on components, 
        # assign messages to them, then delete unused threads.
        
        # Filter components to only those containing actual messages in our DB
        # (Graph contains ghost nodes from References)
        
        valid_components = []
        for comp in components:
            db_pks = []
            for node in comp:
                if node in mid_to_pk:
                    db_pks.append(mid_to_pk[node])
            if db_pks:
                valid_components.append(db_pks)
        
        print(f"     -> Found {len(valid_components)} components with DB messages.")
        
        # Sort components by earliest message time?
        # Create Threads
        print("   - Creating New Threads...")
        
        # We will bulk insert threads.
        # For each component, we need: Subject, ContactID, Status.
        # Subject: Use subject of the EARLIEST message.
        # Contact: Use contact of the EARLIEST message.
        
        new_threads_data = [] # List of dicts
        
        # Map component_index -> list of msg_pks
        comp_map = {} 
        
        for i, pks in enumerate(valid_components):
            # Sort PKs by sent_at
            # We need to look up sent_at
            pks.sort(key=lambda pk: pk_to_data[pk]['sent_at'] or str(pk))
            
            earliest_pk = pks[0]
            data = pk_to_data[earliest_pk]
            
            new_threads_data.append({
                'subject': data['subject'],
                'contact_id': data['contact_id'],
                'status': 'active'
            })
            comp_map[i] = pks
            
        # Bulk Insert Threads
        # Insert in chunks of 1000
        print(f"     -> Installing {len(new_threads_data)} threads into DB...")
        
        created_thread_ids = []
        stmt_insert = text("INSERT INTO threads (subject, contact_id, status, created_at) VALUES (:subject, :contact_id, :status, NOW()) RETURNING id")
        
        # Single inserts for safety (returning id)
        # 15k-40k rows. 1 min.
        for i, tdata in enumerate(new_threads_data):
            # handle safe subject (remove null chars etc if any?)
            # Postgres usually handles text fine.
            tid = conn.execute(stmt_insert, tdata).scalar()
            created_thread_ids.append(tid)
            
            if i % 1000 == 0:
                print(f"       .. {i}/{len(new_threads_data)}", end='\r')
        print(f"       .. Done.")
        
        # Assign Messages to New Threads
        print("   - Linking Messages to New Threads...")
        
        msg_updates = []
        
        for i, tid in enumerate(created_thread_ids):
            pks = comp_map[i]
            for pk in pks:
                msg_updates.append({'pk': pk, 'tid': tid})
                
        # Batch Update
        print(f"     -> Updating {len(msg_updates)} messages...")
        stmt_update = text("UPDATE messages SET thread_id = :tid WHERE id = :pk")
        
        batch_size = 5000
        for i in range(0, len(msg_updates), batch_size):
            batch = msg_updates[i:i+batch_size]
            conn.execute(stmt_update, batch)
            print(f"       .. {min(i+batch_size, len(msg_updates))}", end='\r')
        print("")
        
        conn.commit()
        
        # Cleanup Old Threads
        print("   - 🧹 Cleaning up unused threads...")
        conn.execute(text("DELETE FROM threads WHERE id NOT IN (SELECT DISTINCT thread_id FROM messages)"))
        conn.commit()
        
        # Recalc Stats
        print("   - 📊 Recalculating Thread Stats...")
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
        
    print("✅ FORCE RESET COMPLETE.")

if __name__ == "__main__":
    force_reset_threads()
