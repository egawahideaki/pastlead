from app.models import engine, Thread
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

SessionLocal = sessionmaker(bind=engine)
session = SessionLocal()

def debug_status():
    print("🔍 Database Status Debugger")
    
    with engine.connect() as conn:
        # 1. Check Total Threads
        total = conn.execute(text("SELECT count(*) FROM threads")).scalar()
        print(f"Total Threads: {total}")
        
        # 2. Check Status Breakdown
        print("\n--- Status Breakdown ---")
        rows = conn.execute(text("SELECT status, count(*) FROM threads GROUP BY status")).fetchall()
        for r in rows:
            print(f"Status '{r[0]}': {r[1]}")
            
        # 3. Check Message Counts sample
        print("\n--- Msg Count Sample (Active vs Ignored) ---")
        rows = conn.execute(text("SELECT id, message_count, status FROM threads LIMIT 10")).fetchall()
        for r in rows:
            print(f"ID: {r[0]} | Count: {r[1]} | Status: {r[2]}")
            
if __name__ == "__main__":
    debug_status()
