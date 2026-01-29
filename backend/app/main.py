from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
from fastapi.middleware.cors import CORSMiddleware
from .models import SessionLocal, Contact, Message, Thread, get_db, IgnoreList


from . import search # Import search module
from .utils import decode_mime

app = FastAPI(title="PastLead API")
app.include_router(search.router) # Register Search Router
from . import settings
app.include_router(settings.router)


# CORS setup for Frontend communication
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def read_root():
    return {"message": "Welcome to PastLead API"}

@app.get("/stats")
def get_stats(db: Session = Depends(get_db)):
    contact_count = db.query(Contact).count()
    message_count = db.query(Message).count()
    return {
        "contacts": contact_count,
        "messages": message_count
    }



@app.get("/messages")
def get_messages(skip: int = 0, limit: int = 50, db: Session = Depends(get_db)):
    # Filter by Active threads only
    messages = db.query(Message)\
        .join(Message.thread)\
        .filter(Thread.status == 'active')\
        .order_by(Message.sent_at.desc())\
        .offset(skip).limit(limit).all()
    
    # Simple serialization (avoiding excessive pydantic boilerplates for now)
    return [
        {
            "id": m.id,
            "subject": decode_mime(m.thread.subject) if m.thread else "(No Subject)",
            "from": decode_mime(m.contact.name) if m.contact and m.contact.name else m.contact.email if m.contact else "Unknown",
            "date": m.sent_at,
            "snippet": (m.content_body[:100] + "...") if m.content_body else ""
        }
        for m in messages
    ]

@app.get("/threads")
def get_threads(skip: int = 0, limit: int = 50, sort: str = "score", db: Session = Depends(get_db)):
    query = db.query(Thread).filter(Thread.status == 'active')
    
    if sort == "date":
        query = query.order_by(Thread.last_message_at.desc())
    else: # default score
        query = query.order_by(Thread.score.desc())
        
    threads = query.offset(skip).limit(limit).all()
    
    return [
        {
            "id": t.id,
            "subject": decode_mime(t.subject),
            "message_count": t.message_count,
            "last_message_at": t.last_message_at,
            "score": float(t.score) if t.score else 0.0, 
            "metadata": t.metadata_ if t.metadata_ else {},
            "contact_email": t.contact.email if t.contact else "Unknown"
        }
        for t in threads
    ]


@app.get("/threads/{thread_id}/messages")
def get_thread_messages(thread_id: int, db: Session = Depends(get_db)):
    messages = db.query(Message)\
        .filter(Message.thread_id == thread_id)\
        .order_by(Message.sent_at.asc())\
        .all()
    
    return [
        {
            "id": m.id,
            "sender_type": m.sender_type,
            "sender_name": decode_mime(m.contact.name) if m.contact and m.contact.name else m.contact.email if m.contact else "Unknown",
            "date": m.sent_at,
            "body": m.content_body,
            "message_id": m.message_id
        }
        for m in messages
    ]

from .ai_summary import generate_thread_summary

@app.get("/threads/{thread_id}/summary")
def get_thread_summary(thread_id: int, db: Session = Depends(get_db)):
    # 1. Fetch messages
    messages = db.query(Message)\
        .filter(Message.thread_id == thread_id)\
        .order_by(Message.sent_at.asc())\
        .all()
    
    if not messages:
        return {"summary": "No messages found.", "status": "No Data"}

    # 2. Convert to format expected by AI
    # Strategy: Head(1) + Middle(Condensed) + Tail(3)
    
    total_msgs = len(messages)
    selected_messages = []
    
    if total_msgs <= 5:
        # If few messages, use all of them
        msg_subset = messages
        for m in msg_subset:
            selected_messages.append({
                "sender_name": decode_mime(m.contact.name) if m.contact and m.contact.name else "Unknown",
                "date": m.sent_at.strftime("%Y-%m-%d %H:%M"),
                "body": m.content_body or "",
                "type": "full"
            })
    else:
        # Head: First message (Full context)
        first_msg = messages[0]
        selected_messages.append({
            "sender_name": decode_mime(first_msg.contact.name) if first_msg.contact and first_msg.contact.name else "Unknown",
            "date": first_msg.sent_at.strftime("%Y-%m-%d %H:%M"),
            "body": first_msg.content_body or "",
            "type": "full"
        })
        
        # Middle: Extract snippets
        # Exclude first 1 and last 3
        middle_msgs = messages[1:-3]
        for m in middle_msgs:
            # Extract first line or first 100 chars as snippet
            body_snippet = (m.content_body or "").strip().split('\n')[0][:100] + "..."
            selected_messages.append({
                "sender_name": decode_mime(m.contact.name) if m.contact and m.contact.name else "Unknown",
                "date": m.sent_at.strftime("%Y-%m-%d %H:%M"),
                "body": body_snippet,
                "type": "summary" # Flag to helper to treat as summary
            })
            
        # Tail: Last 3 messages (Full context for status/next action)
        tail_msgs = messages[-3:]
        for m in tail_msgs:
            selected_messages.append({
                "sender_name": decode_mime(m.contact.name) if m.contact and m.contact.name else "Unknown",
                "date": m.sent_at.strftime("%Y-%m-%d %H:%M"),
                "body": m.content_body or "",
                "type": "full"
            })

    # Log info for debugging
    print(f"Generating summary for thread {thread_id}. Strategy used: Head(1)+Middle({len(messages)-4})+Tail(3) if >5.")

    # 3. Generate summary using local LLM
    try:
        result = generate_thread_summary(selected_messages)
        return result
    except Exception as e:
        print(f"Error generating summary: {e}")
        return {"summary": "Error during generation", "status": "Error"}


from sqlalchemy import func, desc

@app.get("/contacts")
def get_contacts(
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db)
):
    """
    Get contacts managed by person, sorted by importance (max thread score).
    Includes aggregated stats and list of threads.
    """
    try:
        # Subquery to aggregate metrics per contact
        # We want contacts that have at least one thread
        
        # 1. Get metrics per contact
        # max_score, thread_count, last_active
        stats_query = db.query(
            Thread.contact_id,
            func.max(Thread.score).label("max_score"),
            func.count(Thread.id).label("thread_count"),
            func.max(Thread.last_message_at).label("last_active")
        ).group_by(Thread.contact_id).subquery()

        # 1.1 Correct "First Active" by finding the oldest message for this contact
        first_msg_query = db.query(
            Message.contact_id,
            func.min(Message.sent_at).label("first_active_real")
        ).group_by(Message.contact_id).subquery()


        # 1.5 Get Ignore List
        ignore_items = db.query(IgnoreList).all()
        ignored_emails = [item.value for item in ignore_items if item.type == 'email']
        ignored_domains = [item.value for item in ignore_items if item.type == 'domain']

        # 2. Join with Contact table and Order by max_score DESC
        # Note: stats_query.c accesses columns of the subquery
        query = db.query(Contact, stats_query, first_msg_query)\
            .join(stats_query, Contact.id == stats_query.c.contact_id)\
            .outerjoin(first_msg_query, Contact.id == first_msg_query.c.contact_id)

            
        if ignored_emails:
            query = query.filter(Contact.email.notin_(ignored_emails))
        
        # Domain filtering (safer to do in Python if list is small, but SQL is faster)
        # For domains, using NOT LIKE might be heavy if many domains. 
        # But for MVP, we iterate conditions or just Python filter. 
        # Let's simple SQL filter for strict matches if domain extraction is easy?
        # Actually, "value" in ignore list is "gmail.com"
        # We want to exclude email ending with "@gmail.com"
        
        for domain in ignored_domains:
            query = query.filter(Contact.email.notilike(f"%@{domain}"))

        results = query.order_by(desc(stats_query.c.max_score))\
            .limit(limit).offset(offset).all()


        contacts_data = []
        
        for row in results:
            # row is (Contact, contact_id, max_score, thread_count, last_active, first_active)
            # Because we queried (Contact, stats_query)
            contact = row[0]
            # row[1] is contact_id
            max_score = row.max_score
            thread_count = row.thread_count
            last_active = row.last_active
            first_active = row.first_active_real


            # Fetch individual threads for this contact (for accordion view)
            threads = db.query(Thread)\
                .filter(Thread.contact_id == contact.id)\
                .order_by(Thread.last_message_at.desc())\
                .all()
                
            thread_list = [{
                "id": t.id,
                "subject": decode_mime(t.subject) if t.subject else "(No Subject)",
                "score": t.score or 0.0,
                "last_message_at": t.last_message_at.strftime("%Y-%m-%d %H:%M") if t.last_message_at else "",
                "message_count": t.message_count
            } for t in threads]

            # Determine "Representative Thread Title" (Top score one)
            top_thread = max(threads, key=lambda x: x.score or 0.0) if threads else None
            top_title = decode_mime(top_thread.subject) if top_thread and top_thread.subject else "No Thread"

            contacts_data.append({
                "id": contact.id,
                "name": decode_mime(contact.name or "Unknown"),
                "email": contact.email,
                "max_score": float(max_score or 0.0),
                "thread_count": thread_count,
                "last_active": last_active.strftime("%Y-%m-%d") if last_active else None,
                "first_active": first_active.strftime("%Y-%m-%d") if first_active else None,
                "top_thread_title": top_title,
                "threads": thread_list
            })

        return contacts_data
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"Error in get_contacts: {e}")
        # Return empty list or error compliant structure
        return []
