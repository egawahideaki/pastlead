from app.models import engine
from sqlalchemy import text

def force_activate():
    print("🔓 Force Activating All Threads...")
    with engine.connect() as conn:
        result = conn.execute(text("UPDATE threads SET status = 'active'"))
        conn.commit()
        print(f"   -> Updated {result.rowcount} threads to 'active'.")

if __name__ == "__main__":
    force_activate()
