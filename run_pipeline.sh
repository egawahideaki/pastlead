#!/bin/bash

# Configuration
MBOX_FILE="すべてのメール（迷惑メール、ゴミ箱のメールを含む）-002.mbox"
LOG_FILE="pipeline.log"

# Function to log messages with timestamp
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

cd "$(dirname "$0")"
log "🚀 Starting PastLead Data Pipeline..."

# 1. Environment Setup
log "🔹 Step 1: Environment Check"
if [ ! -d "venv" ]; then
    log "Creating Python virtual environment..."
    python3 -m venv venv
    source venv/bin/activate
    pip install -r backend/requirements.txt
else
    source venv/bin/activate
fi
export PYTHONPATH=$PYTHONPATH:$(pwd)/backend

# 2. DB Check & Migration
log "🔹 Step 2: Database Check"
# Ensure DB is up
if ! docker ps | grep -q knowhow_db; then
    log "Starting Database..."
    docker-compose up -d
    sleep 5
fi

# Ensure pgvector extension
log "Ensuring pgvector extension..."
docker exec -i knowhow_db psql -U user -d knowhow_db -c "CREATE EXTENSION IF NOT EXISTS vector;" >> "$LOG_FILE" 2>&1

# Ensure schema migration (for status column)
# We run a small script to ensure tables match models
python -c "from app.models import create_tables; create_tables()" >> "$LOG_FILE" 2>&1
# Also ensure status column exists if table already existed (idempotent check)
python -c "from app.models import engine; from sqlalchemy import text; 
with engine.connect() as conn: 
    conn.execute(text('ALTER TABLE threads ADD COLUMN IF NOT EXISTS status TEXT DEFAULT ''active''')); 
    conn.commit();" >> "$LOG_FILE" 2>&1

# 3. Import (Fast Mode + Resume Support)
log "🔹 Step 3: Mbox Import"
if [ ! -f "$MBOX_FILE" ]; then
    log "❌ Error: Mbox file '$MBOX_FILE' not found."
    exit 1
fi

log "Running High-Speed Import (This may take time)..."
# Run fast import. Not in background, blocking here to ensure sequence.
# -u for unbuffered, piped to log
python -u backend/scripts/import_mbox_fast.py "$MBOX_FILE" 2>&1 | tee -a "$LOG_FILE"

# 4. Thread Reconstruction
log "🔹 Step 4: Thread Reconstruction"
# 3.5 Subject Recovery (Fix Missing Subjects)
log "🔹 Step 3.5: Subject Recovery"
log "Scanning mbox for missing subjects..."
python -u backend/scripts/recover_subjects.py "$MBOX_FILE" 2>&1 | tee -a "$LOG_FILE"

# 4. Thread Reconstruction
log "🔹 Step 4: Thread Reconstruction"
log "Start Strict V2 Reconstruction (Header + Subject Guard)..."
python -u backend/scripts/reconstruct_threads.py 2>&1 | tee -a "$LOG_FILE"

# 5. Filtering (Noise Reduction)
log "🔹 Step 5: Filtering & Noise Reduction"
log "Identifying important threads (Multiple messages, non-bulk)..."
python -u backend/scripts/run_filtering.py 2>&1 | tee -a "$LOG_FILE"

# 6. Content Extraction
log "🔹 Step 6: Targeted Content Extraction"
log "Extracting bodies for active threads only..."
python -u backend/scripts/extract_bodies.py 2>&1 | tee -a "$LOG_FILE"

# 7. Vectorization
log "🔹 Step 7: Vectorization (Embedding Generation)"
log "Generating 768d vectors for extracted content..."
python -u backend/scripts/generate_embeddings.py 2>&1 | tee -a "$LOG_FILE"

# 8. Feature Extraction
log "🔹 Step 8: Feature Extraction & Scoring"
log "Extracting economic values and calculating initial scores..."
python -u backend/scripts/extract_features.py 2>&1 | tee -a "$LOG_FILE"

log "✅ Pipeline Completed Successfully!"
log "Next: Run 'npm run dev' in frontend/ directory to view results."
