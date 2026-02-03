from sqlalchemy import create_engine, MetaData, Table, Column, String, Integer, DateTime, Boolean, Numeric, ForeignKey, Text, Index, BigInteger, Float, JSON, text
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
# SQLite Setup
DEFAULT_DB_URL = "sqlite:///./pastlead.db"
DATABASE_URL = os.getenv("DATABASE_URL", DEFAULT_DB_URL)

# Ensure data directory exists for SQLite
if "sqlite" in DATABASE_URL:
    db_path = DATABASE_URL.replace("sqlite:///", "")
    os.makedirs(os.path.dirname(db_path), exist_ok=True)

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {})

# Session Factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

Base = declarative_base()

class Contact(Base):
    __tablename__ = "contacts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String, unique=True, index=True, nullable=False)
    name = Column(String, nullable=True)
    company_name = Column(String, nullable=True)
    closeness_score = Column(Float, default=0)
    last_contacted_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    threads = relationship("Thread", back_populates="contact")
    messages = relationship("Message", back_populates="contact")

class Thread(Base):
    __tablename__ = "threads"

    id = Column(Integer, primary_key=True, autoincrement=True)
    contact_id = Column(Integer, ForeignKey("contacts.id", ondelete="CASCADE"), nullable=False)
    subject = Column(String, nullable=True)
    message_count = Column(Integer, default=0)
    last_message_at = Column(DateTime(timezone=True))
    status = Column(String, default='active') # active, ignored, pending_body
    score = Column(Float, default=0)
    metadata_ = Column(JSON, default={})
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    contact = relationship("Contact", back_populates="threads")
    messages = relationship("Message", back_populates="thread", cascade="all, delete-orphan")
    
    __table_args__ = (Index('idx_threads_contact_id', 'contact_id'),)

class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    thread_id = Column(Integer, ForeignKey("threads.id", ondelete="CASCADE"), nullable=False)
    contact_id = Column(Integer, ForeignKey("contacts.id", ondelete="CASCADE"), nullable=False)
    message_id = Column(String, unique=True, nullable=False)
    sender_type = Column(String, nullable=False)
    content_body = Column(Text, nullable=True)
    subject = Column(String, nullable=True) # Added for rigorous threading
    # content_vector = Column(Vector(768)) # Gemini Standard - Removed for SQLite compatibility
    sent_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    thread = relationship("Thread", back_populates="messages")
    contact = relationship("Contact", back_populates="messages")
    
    metadata_ = Column(JSON, default={})
    
    __table_args__ = (
        Index('idx_messages_thread_id', 'thread_id'),
        Index('idx_messages_contact_id', 'contact_id'),
    )

class IgnoreList(Base):
    __tablename__ = "ignore_list"

    id = Column(Integer, primary_key=True, autoincrement=True)
    value = Column(Text, nullable=False, unique=True) # The email or domain
    type = Column(Text, nullable=False) # 'email' or 'domain'
    created_at = Column(DateTime(timezone=True), server_default=func.now())


def create_tables():
    Base.metadata.create_all(bind=engine)
