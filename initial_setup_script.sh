#!/bin/bash

echo "🚀 Starting Project Setup for Email AI Assistant..."

# 1. Directory Structure
mkdir -p backend/app
mkdir -p backend/scripts
mkdir -p frontend

# 2. Docker Compose
echo "📝 Creating docker-compose.yml..."
cat <<EOF > docker-compose.yml
services:
  db:
    image: pgvector/pgvector:pg16
    container_name: knowhow_db
    environment:
      POSTGRES_USER: user
      POSTGRES_PASSWORD: password
      POSTGRES_DB: knowhow_db
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data

volumes:
  postgres_data:
EOF

# 3. Backend Requirements
echo "📝 Creating backend/requirements.txt..."
cat <<EOF > backend/requirements.txt
fastapi
uvicorn[standard]
sqlalchemy
psycopg2-binary
pgvector
pydantic
pydantic-settings
python-dotenv
asyncpg
BeautifulSoup4
lxml
EOF

# 4. Backend .env
echo "📝 Creating backend/.env..."
cat <<EOF > backend/.env
DATABASE_URL=postgresql+psycopg2://user:password@localhost:5432/knowhow_db
EOF

# 5. DB Models (Fixed: Postgres explicit connection)
echo "📝 Creating backend/app/models.py..."
cat <<EOF > backend/app/models.py
from sqlalchemy import create_engine, MetaData, Table, Column, String, Integer, DateTime, Boolean, Numeric, ForeignKey, Text, Index, BigInteger
from sqlalchemy.orm import declarative_base, relationship, sessionmaker
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func
from pgvector.sqlalchemy import Vector
import os
from dotenv import load_dotenv
from pathlib import Path

# Explicitly load .env
env_path = Path(__file__).resolve().parent.parent / '.env'
load_dotenv(dotenv_path=env_path)

# Verify DATABASE_URL
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    DATABASE_URL = "postgresql+psycopg2://user:password@localhost:5432/knowhow_db"
    print(f"Warning: DATABASE_URL not set, using default: {DATABASE_URL}")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

class Contact(Base):
    __tablename__ = "contacts"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    email = Column(Text, unique=True, index=True, nullable=False)
    name = Column(Text, nullable=True)
    company_name = Column(Text, nullable=True)
    closeness_score = Column(Numeric(5, 2), default=0)
    last_contacted_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    threads = relationship("Thread", back_populates="contact")
    messages = relationship("Message", back_populates="contact")

class Thread(Base):
    __tablename__ = "threads"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    contact_id = Column(BigInteger, ForeignKey("contacts.id", ondelete="CASCADE"), nullable=False)
    subject = Column(Text, nullable=True)
    message_count = Column(Integer, default=0)
    last_message_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    contact = relationship("Contact", back_populates="threads")
    messages = relationship("Message", back_populates="thread", cascade="all, delete-orphan")
    
    __table_args__ = (Index('idx_threads_contact_id', 'contact_id'),)

class Message(Base):
    __tablename__ = "messages"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    thread_id = Column(BigInteger, ForeignKey("threads.id", ondelete="CASCADE"), nullable=False)
    contact_id = Column(BigInteger, ForeignKey("contacts.id", ondelete="CASCADE"), nullable=False)
    message_id = Column(Text, unique=True, nullable=False)
    sender_type = Column(Text, nullable=False)
    content_body = Column(Text, nullable=True)
    content_vector = Column(Vector(768)) # Gemini Standard
    sent_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    thread = relationship("Thread", back_populates="messages")
    contact = relationship("Contact", back_populates="messages")
    
    __table_args__ = (
        Index('idx_messages_thread_id', 'thread_id'),
        Index('idx_messages_contact_id', 'contact_id'),
    )

def create_tables():
    Base.metadata.create_all(bind=engine)
EOF

# 6. Import Script (Fixed: Filter logic & Postgres UPSERT)
echo "📝 Creating backend/scripts/import_mbox.py..."
cat <<EOF > backend/scripts/import_mbox.py
import mailbox
import email
from email.utils import parseaddr, parsedate_to_datetime
import os
import argparse
from sqlalchemy.orm import Session
from app.models import engine, SessionLocal, Contact, Thread, Message, create_tables
from sqlalchemy.dialects.postgresql import insert
from datetime import datetime

BATCH_SIZE = 1000
IGNORE_DOMAINS = ["noreply", "no-reply", "donotreply", "notification", "info", "mailer-daemon"]

def is_valid_email(email_addr):
    if not email_addr: return False
    if any(ignore in email_addr.lower() for ignore in IGNORE_DOMAINS): return False
    return True

def is_human_email(msg):
    if 'List-Unsubscribe' in msg: return False
    if 'Precedence' in msg and msg['Precedence'] in ['bulk', 'list', 'junk']: return False
    from_header = msg.get('From')
    if not from_header: return False
    name, addr = parseaddr(from_header)
    if not is_valid_email(addr): return False
    return True

def get_or_create_contact(session, email_addr, name):
    stmt = insert(Contact).values(
        email=email_addr, name=name, closeness_score=0
    ).on_conflict_do_update(
        index_elements=['email'],
        set_=dict(name=name, updated_at=datetime.now())
    ).returning(Contact.id)
    return session.execute(stmt).scalar()

def process_mbox(file_path):
    print(f"Opening mbox: {file_path}")
    print(f"DB Engine: {engine.dialect.name}")
    create_tables()
    session = SessionLocal()
    count = 0
    total = 0
    
    try:
        mbox = mailbox.mbox(file_path)
        for message in mbox:
            try:
                if not is_human_email(message): continue
                
                msg_id = message.get('Message-ID', '').strip()
                if not msg_id: continue
                
                date_str = message.get('Date')
                if not date_str: continue
                sent_at = parsedate_to_datetime(date_str)
                
                from_name, from_addr = parseaddr(message.get('From'))
                
                # Contact
                contact_id = get_or_create_contact(session, from_addr, from_name)
                
                # Simple Threading (Create new for now)
                subject = message.get('Subject', '')
                thread = Thread(contact_id=contact_id, subject=subject, last_message_at=sent_at)
                session.add(thread)
                session.flush()
                
                # Message
                db_msg = Message(
                    thread_id=thread.id,
                    contact_id=contact_id,
                    message_id=msg_id,
                    sender_type='contact',
                    sent_at=sent_at,
                    content_body="Pending extraction" 
                )
                session.add(db_msg)
                
                count += 1
                total += 1
                if count >= BATCH_SIZE:
                    session.commit()
                    print(f"Processed {total} messages...")
                    count = 0
            except Exception as e:
                # print(f"Skipping msg: {e}")
                continue
                
        session.commit()
        print(f"Finished! Total: {total}")
    except Exception as e:
        print(f"Critical Error: {e}")
    finally:
        session.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mbox_path")
    args = parser.parse_args()
    if os.path.exists(args.mbox_path):
        process_mbox(args.mbox_path)
    else:
        print("File not found.")
EOF

# 7. Frontend Setup (One-liner to be run manually if needed, or by agent later)
# echo "run 'npx create-next-app@latest frontend' later..."

echo "✅ Setup script completed. ready to run 'docker-compose up -d' and 'pip install -r backend/requirements.txt'"
