from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.models import get_db, Message, Thread, Contact
from sentence_transformers import SentenceTransformer
from .utils import decode_mime
import os

router = APIRouter()

# Load model (Global cache)
# This loads on startup, might be slow.
# For production, use a separate service or lighter model loading.
# Since we reuse the same container, it's fine.
_model = None

def get_model():
    global _model
    if _model is None:
        print("🧠 Loading Semantic Search Model...")
        _model = SentenceTransformer('sentence-transformers/paraphrase-multilingual-mpnet-base-v2')
    return _model

@router.get("/search")
def semantic_search(
    q: str, 
    limit: int = 10, 
    db: Session = Depends(get_db)
):
    if not q:
        return []
        
    model = get_model()
    
    # 1. Vectorize Query
    query_vector = model.encode(q).tolist()
    
    # 2. Search Database (using pgvector)
    # Cosine distance (<->) default for this model in pgvector usually uses L2 (<->) or Cosine (<=>)?
    # pgvector operators:
    # <-> : L2 distance
    # <=> : Cosine distance
    # <#> : Inner product
    # We used 'vector_cosine_ops' in index, so <=> is best.
    
    # However, SQLAlchemy ORM doesn't support <=> directly easily in older versions.
    # We use order_by(Message.content_vector.cosine_distance(query_vector))
    
    results = db.query(Message, Thread, Contact)\
        .join(Thread, Message.thread_id == Thread.id)\
        .join(Contact, Message.contact_id == Contact.id)\
        .filter(Message.content_vector.isnot(None))\
        .order_by(Message.content_vector.cosine_distance(query_vector))\
        .limit(limit)\
        .all()
        
    # 3. Format Response
    response = []
    for msg, thread, contact in results:
        # Avoid duplicate threads if possible? 
        # But users might want specific message context.
        response.append({
            "message_id": msg.id,
            "thread_id": thread.id,
            "subject": decode_mime(thread.subject) if thread.subject else "(No Subject)",
            "body": msg.content_body[:200] + "..." if msg.content_body else "",
            "date": msg.sent_at,
            "sender": decode_mime(contact.name) if contact.name else contact.email,
            "score": float(thread.score) if thread.score else 0
        })
        
    return response
