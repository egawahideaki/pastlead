import re
import networkx as nx
from sqlalchemy import text
from app.models import engine
from collections import defaultdict

def normalize_msg_id(mid):
    if not mid: return None
    # Remove < and >
    return mid.strip().strip('<>')

def normalize_subject(subject):
    if not subject: return ""
    # Remove Re:, Fwd:, FW:, etc. (case insensitive)
    # Also ignore brackets [] often used by mailing lists or services
    s = re.sub(r'([\[\(].*?[\]\)])', '', subject) 
    s = re.sub(r'^(re|fwd|fw|aw|antw|回复|回覆|転送|返信)[:：]\s*', '', s, flags=re.IGNORECASE).strip()
    return s.strip()

def reconstruct_threads_hybrid():
    print("🧵 Starting HYBRID Thread Reconstruction...")
    
    with engine.connect() as conn:
        print("   - Fetching Message Data...")
        
        # Load all messages
        stmt = text("""
            SELECT m.id, m.message_id, m.metadata_->>'In-Reply-To', m.metadata_->>'References', 
                   m.thread_id, COALESCE(t.subject, '')
            FROM messages m
            JOIN threads t ON m.thread_id = t.id
        """)
        
        rows = conn.execute(stmt).fetchall()
        print(f"     -> Loaded {len(rows)} messages.")
        
        # Graph Construction
        G = nx.Graph()
        
        # We need a way to lookup message PK by Message-ID (for header linking)
        mid_to_pk = {}
        pk_to_data = {} # pk -> {subject, sent_at...}
        
        # 1. Header Linking Phase
        for row in rows:
            pk = row[0]
            raw_mid = row[1]
            in_reply_to = row[2]
            references = row[3]
            subject = row[5]
            
            mid = normalize_msg_id(raw_mid)
            if not mid: 
                # If no Message-ID, we can't link by header, but we add to graph as isolated node
                # We use PK as node ID for these? No, consistency is hard.
                # Let's use a dummy ID like "PK:{pk}"
                mid = f"PK:{pk}"
            
            G.add_node(mid, pk=pk, subject=normalize_subject(subject))
            mid_to_pk[mid] = pk
            pk_to_data[pk] = {'mid': mid, 'subject': normalize_subject(subject)}
            
            # Header Edges
            if mid.startswith("PK:"): continue # Can't have header links
            
            refs = []
            if in_reply_to: refs.append(in_reply_to)
            if references: refs.extend(references.split())
            
            for r in refs:
                ref_mid = normalize_msg_id(r)
                if ref_mid:
                    G.add_edge(mid, ref_mid)

        print(f"     -> built Graph: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges.")
        
        # --- Strict V3: Subject Consistency Pruning ---
        # Issue: Generic System IDs or Contact Forms can link unrelated conversations.
        # Solution: If two linked messages have TOTALLY different subjects, prune the edge.
        
        print("   - Pruning suspicious edges based on Subject Mismatch...")
        
        edges_to_remove = []
        
        def normalize_for_compare(text):
            if not text: return ""
            # Remove Re:, Fwd: etc.
            s = re.sub(r'^(re|fwd|fw|aw|antw|回复|回覆|転送|返信)[:：]\s*', '', text, flags=re.IGNORECASE).strip()
            # Remove spaces
            return re.sub(r'\s+', '', s.lower())

        def get_bigrams(normalized_text):
            if len(normalized_text) < 2: return set([normalized_text])
            return set(normalized_text[i:i+2] for i in range(len(normalized_text)-1))

        print("   - Pruning edges (detailed log):")
        
        for u, v in G.edges():
            raw_u = G.nodes[u].get('subject', '') or ""
            raw_v = G.nodes[v].get('subject', '') or ""
            
            if not raw_u or not raw_v: continue
            
            norm_u = normalize_for_compare(raw_u)
            norm_v = normalize_for_compare(raw_v)
            
            if not norm_u or not norm_v: continue
            
            # If exact match after normalization, keep
            if norm_u == norm_v: continue
            
            # If one contains the other (e.g. "ProjectA" vs "ProjectA Update") -> Keep
            # But only if length difference is not huge
            if norm_u in norm_v or norm_v in norm_u:
                 # Check length ratio to avoid "A" matching "Apple"
                 len_min = min(len(norm_u), len(norm_v))
                 len_max = max(len(norm_u), len(norm_v))
                 if len_min / len_max > 0.3: # At least 30% length
                     continue

            # N-gram Jaccard Similarity
            bigrams_u = get_bigrams(norm_u)
            bigrams_v = get_bigrams(norm_v)
            
            intersection = bigrams_u.intersection(bigrams_v)
            union = bigrams_u.union(bigrams_v)
            
            jaccard = len(intersection) / len(union) if union else 0.0
            
            # Threshold 0.3: Allow some variation but cut total mismatch
            # "Meeting" (me,ee,et,ti,in,ng) vs "Invoice" (in,nv,vo,oi,ic,ce) -> 0.
            if jaccard < 0.3: 
                 # DEBUG: Print what we are cutting
                 print(f"     ✂️ CUT: '{raw_u}' <//> '{raw_v}' (Sim: {jaccard:.2f})")
                 edges_to_remove.append((u, v))
                 
        G.remove_edges_from(edges_to_remove)
        print(f"     -> Pruned {len(edges_to_remove)} edges due to subject mismatch.")
        
        # 2. Subject Linking Phase (DISABLED for Strict Mode V2)
        # We previously merged threads with same subject, but this caused massive "super-threads"
        # mixing unrelated people (e.g. "Meeting request", "Thank you").
        # Detailed analysis showed that aggressive subject normalization caused this.
        # To ensure privacy and correctness, we will rely 100% on Message-ID headers (In-Reply-To/References).
        # This causes some fragmentation (if headers are missing), but that is better than mixing data.
        
        print("   - Subject Linking DISABLED. Using strict header-based threading only.")
        
        # Determine components purely from the Header Graph (G)
        components = list(nx.connected_components(G))
        print(f"     -> Identified {len(components)} distinct threads.")
        
        # Update DB
        # We assign a new unique Thread ID to each component.
        # We can recycle existing IDs if possible, but to ensure clean break, let's create new mapping.
        
        # To avoid creating millions of new Thread rows, we:
        # 1. Identify "Leader" of component (min PK).
        # 2. Use Leader's current Thread ID if it's "Clean" (i.e. only used by this component).
        #    But cleaner to just map: LeaderPK -> TargetThreadID.
        #    If Thread ID X is reused by multiple components, we must split.
        
        # Let's just blindly update all messages.
        # TargetID = Thread ID of the Leader Message.
        # If multiple components map to same TargetID, only the first one keeps it.
        # Others get NEW Thread IDs (we insert new Thread rows).
        
        updates = []
        
        # Cache existing Thread Info to minimize inserts
        # thread_id -> is_taken (bool)
        taken_threads = set()
        
        # List of (LeaderPK, [AllPKs])
        groups = []
        for comp in components:
            # Get PKs
            pks = []
            for n in comp:
                if n in mid_to_pk:
                    pks.append(mid_to_pk[n])
            if not pks: continue
            
            leader = min(pks)
            groups.append((leader, pks))
            
        # We need to look up the current thread_id of each leader
        # We can do this in bulk or just query.
        # rows has (id, ..., thread_id). We can Map id->thread_id.
        pk_to_tid = {r[0]: r[4] for r in rows}
        
        inserts = [] # New threads to create
        msg_updates = [] # (mid_pk, new_tid)
        
        print("   - Allocating Thread IDs...")
        
        # Batch insert optimization?
        # It's hard to get IDs back without individual inserts or complex RETURNING logic.
        # Let's try to REUSE as much as possible.
        
        reused_count = 0
        new_count = 0
        
        for leader, members in groups:
            curr_tid = pk_to_tid.get(leader)
            
            topic = pk_to_data[leader]['subject']
            
            if curr_tid and curr_tid not in taken_threads:
                # Reuse
                target_tid = curr_tid
                taken_threads.add(curr_tid)
                reused_count += 1
            else:
                # Must create new thread
                # We can't insert immediately if we want efficiency.
                # But we need the ID.
                # For safety and speed, let's just use NEGATIVE integers as placeholders?
                # No, FK constraints.
                
                # Let's insert a Thread and get ID.
                # This is slow n+1.
                # But we have ~15k threads. It's okay.
                # Wait, if we have 50k threads, 50k inserts is slow.
                
                # Faster: Create placeholders in bulk?
                # We need contact_id for the thread. We can use the contact_id of the leader message.
                leader_pk = leader
                # Fetch contact_id for leader
                # Optimization: We should have loaded contact_id in the initial query.
                # But we didn't. Let's do a quick lookup query?
                # Or easier: Default to a "System/Unknown" contact? No, FK.
                # Let's fetch contact_id now. This is inside loop, slow.
                # Better: Modify initial query to load contact_id.
                
                # RESTART STRATEGY: Update the query at top of file, then update here?
                # No, I can't overwrite easily.
                # Hack: Just run a query to get contact_id for this leader.
                cid = conn.execute(text("SELECT contact_id FROM messages WHERE id = :pk"), {"pk": leader_pk}).scalar()
                
                inserts.append({'subject': topic, 'status': 'active', 'cid': cid}) # We'll batch insert later
                new_count += 1
                target_tid = "PENDING"
                
            # Assign this target_tid to all members
            for m in members:
                if target_tid == "PENDING":
                    msg_updates.append({'pk': m, 'pending_idx': len(inserts)-1})
                elif pk_to_tid[m] != target_tid:
                    msg_updates.append({'pk': m, 'tid': target_tid})
                    
        print(f"     -> Reusing {reused_count} threads, Creating {len(inserts)} new threads.")
        
        # Bulk Insert New Threads
        if inserts:
            print("   - Inserting new threads...")
            created_ids = []
            stmt = text("INSERT INTO threads (subject, created_at, status, contact_id) VALUES (:subject, NOW(), :status, :cid) RETURNING id")
            
            for i, item in enumerate(inserts):
                res = conn.execute(stmt, item).scalar()
                created_ids.append(res)
                if i % 1000 == 0:
                    print(f"     ... created {i}/{len(inserts)}", end='\r')
            print(f"     ... created {len(created_ids)}/{len(inserts)}")
            
            # Now map pending_idx to real IDs
            # msg_updates contains 'pending_idx'
            final_updates = []
            for item in msg_updates:
                if 'pending_idx' in item:
                    item['tid'] = created_ids[item['pending_idx']]
                    del item['pending_idx']
                final_updates.append(item)
                
            msg_updates = final_updates

        # Batch Update Messages
        print(f"   - Updating {len(msg_updates)} messages...")
        if msg_updates:
            batch_size = 5000
            for i in range(0, len(msg_updates), batch_size):
                batch = msg_updates[i:i+batch_size]
                conn.execute(
                    text("UPDATE messages SET thread_id = :tid WHERE id = :pk"),
                    batch
                )
                print(f"     ... updated {min(i+batch_size, len(msg_updates))}", end='\r')
            conn.commit()
            print("")
            
        # Cleanup
        print("   - Cleanup...")
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
    
    print("✅ Hybrid Reconstruction Complete.")

if __name__ == "__main__":
    reconstruct_threads_hybrid()
