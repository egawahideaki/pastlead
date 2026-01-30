#!/bin/bash

# PastLead All-in-One Setup Script
# Usage: ./setup.sh /path/to/your/mail.mbox

INPUT_MBOX_PATH=$1

echo "=========================================="
echo "   PastLead: Containerized Setup "
echo "=========================================="

# 1. Check Requirements
if ! command -v docker &> /dev/null; then
    echo "❌ Error: Docker is not installed or not in PATH."
    echo "   Please install Docker Desktop and try again."
    exit 1
fi

MBOX_DIR="./Takeout"
MBOX_FILENAME=""

# 2. Configure Mbox Path (Direct Mount)
if [ -n "$INPUT_MBOX_PATH" ]; then
    if [ ! -f "$INPUT_MBOX_PATH" ]; then
        echo "⚠️  Warning: Mbox file not found at $INPUT_MBOX_PATH"
        echo "   Starting empty."
    else
        # Resolve absolute path
        ABS_MBOX_PATH=$(cd "$(dirname "$INPUT_MBOX_PATH")"; pwd)/$(basename "$INPUT_MBOX_PATH")
        MBOX_DIR=$(dirname "$ABS_MBOX_PATH")
        MBOX_FILENAME=$(basename "$ABS_MBOX_PATH")
        
        echo "📂 Mounting Mbox directory: $MBOX_DIR"
    fi
fi

# 3. Start Services
echo "🚀 Starting Docker containers..."
# Pass the directory as environment variable to docker-compose
export MBOX_DIR="$MBOX_DIR"

docker-compose up -d --build

if [ $? -ne 0 ]; then
    echo "❌ Failed to start containers."
    exit 1
fi

echo "✅ Containers up and running!"

# 4. Data Import Pipeline
if [ -n "$MBOX_FILENAME" ]; then
    echo "🔄 Starting Full Pipeline inside Backend Container..."
    
    # We mounted the directory to /app/Takeout, so the file is at /app/Takeout/filename
    CONTAINER_PATH="/app/Takeout/$MBOX_FILENAME"
    
    # Wait a bit for DB to be potentially ready (though depends_on handles startup, migration might need time)
    sleep 5
    
    # Set PYTHONPATH=. to ensure app module is found
    docker-compose exec -T -e MBOX_DIR="$MBOX_DIR" -e PYTHONPATH=. backend python scripts/full_pipeline.py "$CONTAINER_PATH"
    
    if [ $? -eq 0 ]; then
        echo "✅ Data initialization complete!"
    else
        echo "❌ Data import failed."
    fi
else
    echo "ℹ️  No Mbox file provided. Skipping import."
fi

echo ""
echo "🎉 Setup Finished!"
echo "   - Frontend: http://localhost:3000"
echo "   - Backend:  http://localhost:8000"
