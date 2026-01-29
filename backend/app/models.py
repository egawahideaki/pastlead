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
    status = Column(Text, default='active') # active, ignored, pending_body
    score = Column(Numeric(5, 2), default=0)
    metadata_ = Column(JSONB, default={})
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
    subject = Column(Text, nullable=True) # Added for rigorous threading
    content_vector = Column(Vector(768)) # Gemini Standard
    sent_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    thread = relationship("Thread", back_populates="messages")
    contact = relationship("Contact", back_populates="messages")
    
    metadata_ = Column(JSONB, default={})
    
    __table_args__ = (
        Index('idx_messages_thread_id', 'thread_id'),
        Index('idx_messages_contact_id', 'contact_id'),
        # Add HNSW index for vector similarity search (cosine distance)
        Index(
            'idx_messages_content_vector', 
            content_vector, 
            postgresql_using='hnsw', 
            postgresql_with={'m': 16, 'ef_construction': 64}, 
            postgresql_ops={'content_vector': 'vector_cosine_ops'}
        ),
        # Add GIN index for fast JSONB metadata search
        Index('idx_messages_metadata', metadata_, postgresql_using='gin'),
    )

class IgnoreList(Base):
    __tablename__ = "ignore_list"

    id = Column(Integer, primary_key=True, autoincrement=True)
    value = Column(Text, nullable=False, unique=True) # The email or domain
    type = Column(Text, nullable=False) # 'email' or 'domain'
    created_at = Column(DateTime(timezone=True), server_default=func.now())


def create_tables():
    Base.metadata.create_all(bind=engine)
