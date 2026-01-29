import sys
import os
from sqlalchemy import text
from app.models import engine
from sentence_transformers import SentenceTransformer
import torch
import time

BATCH_SIZE = 32
MODEL_NAME = 'paraphrase-multilingual-mpnet-base-v2'

def get_device():
    if torch.backends.mps.is_available():
        return "mps"
    elif torch.cuda.is_available():
        return "cuda"
    return "cpu"

def generate_embeddings():
    print("🧠 Starting Vectorization (Phase 3)...")
    
    device = get_device()
    print(f"   - Using device: {device}")
    
    print(f"   - Loading model: {MODEL_NAME}...")
    model = SentenceTransformer(MODEL_NAME, device=device)
    
    with engine.connect() as conn:
        print("   - Fetching active messages needing embeddings...")
        
        # Count total
        count_stmt = text("""
            SELECT count(*)
            FROM messages m
            JOIN threads t ON m.thread_id = t.id
            WHERE t.status = 'active'
            AND m.content_body IS NOT NULL
            AND m.content_body != 'Pending extraction'
            AND m.content_body != ''
            AND m.content_vector IS NULL
        """)
        total_count = conn.execute(count_stmt).scalar()
        print(f"     -> Found {total_count} messages to vectorize.")
        
        if total_count == 0:
            print("   - No messages need vectorization.")
            return

        # Fetch IDs and Bodies
        # We fetch in larger chunks to minimize DB roundtrips, but process in mini-batches for GPU/Memory
        FETCH_SIZE = 1000
        offset = 0
        processed = 0
        
        while True:
            stmt = text("""
                SELECT m.id, m.content_body
                FROM messages m
                JOIN threads t ON m.thread_id = t.id
                WHERE t.status = 'active'
                AND m.content_body IS NOT NULL
                AND m.content_body != 'Pending extraction'
                AND m.content_body != ''
                AND m.content_vector IS NULL
                LIMIT :limit
            """)
            
            # Note: OFFSET is bad for performance on large info, but here we are filtering by IS NULL.
            # So as we update, they drop out of the set. So we always just fetch LIMIT.
            # No need for OFFSET!
            
            rows = conn.execute(stmt, {"limit": FETCH_SIZE}).fetchall()
            if not rows:
                break
                
            batch_updates = []
            texts = [row[1] for row in rows]
            ids = [row[0] for row in rows]
            
            # Encode in sub-batches
            for i in range(0, len(rows), BATCH_SIZE):
                sub_texts = texts[i : i + BATCH_SIZE]
                sub_ids = ids[i : i + BATCH_SIZE]
                
                # Encode (returns numpy array)
                embeddings = model.encode(sub_texts, show_progress_bar=False, convert_to_numpy=True)
                
                for msg_id, vector in zip(sub_ids, embeddings):
                    batch_updates.append({
                        "id": msg_id,
                        "vector": vector.tolist()
                    })
            
            # Update DB
            update_stmt = text("UPDATE messages SET content_vector = :vector WHERE id = :id")
            conn.execute(update_stmt, batch_updates)
            conn.commit()
            
            processed += len(rows)
            print(f"     ... vectorized {processed}/{total_count} messages ({(processed/total_count)*100:.1f}%)", end='\r')

    print(f"\n✅ Vectorization Complete. Processed {processed} messages.")

if __name__ == "__main__":
    generate_embeddings()
