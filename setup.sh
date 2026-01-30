#!/bin/bash

# PastLead All-in-One Setup Script
# Usage: ./setup.sh /path/to/your/mail.mbox

MBOX_PATH=$1

echo "=========================================="
echo "   PastLead: Containerized Setup "
echo "=========================================="

# 1. Check Requirements
if ! command -v docker &> /dev/null; then
    echo "❌ Error: Docker is not installed or not in PATH."
    echo "   Please install Docker Desktop and try again."
    exit 1
fi

# 2. Start Services
echo "🚀 Starting Docker containers (DB, Backend, Frontend)..."
echo "   This may take a while on first run (building images)..."
docker-compose up -d --build

if [ $? -ne 0 ]; then
    echo "❌ Failed to start containers."
    exit 1
fi

echo "✅ Containers up and running!"

# 3. Data Import Pipeline (if Mbox provided)
if [ -n "$MBOX_PATH" ]; then
    if [ ! -f "$MBOX_PATH" ]; then
        echo "⚠️  Warning: Mbox file not found at $MBOX_PATH"
        echo "   Skipping import. You can run import later inside the container."
    else
        echo "📦 detected Mbox file. Copying to container volume..."
        # We need to copy mbox to project dir or mount it. 
        # Since we mounted ./Takeout to /app/Takeout in docker-compose, 
        # let's copy the mbox there if it's not already there.
        
        FILENAME=$(basename "$MBOX_PATH")
        DEST_DIR="./Takeout"
        mkdir -p "$DEST_DIR"
        
        # Check if file is outside project, copy it.
        # If it's the same path, ignore.
        ABS_MBOX=$(readlink -f "$MBOX_PATH" 2>/dev/null || echo "$MBOX_PATH")
        ABS_DEST=$(readlink -f "$DEST_DIR/$FILENAME" 2>/dev/null || echo "$DEST_DIR/$FILENAME")
        
        if [ "$ABS_MBOX" != "$ABS_DEST" ]; then
            cp "$MBOX_PATH" "$DEST_DIR/"
            echo "   Copied to $DEST_DIR/$FILENAME"
        fi

        echo "🔄 Starting Full Pipeline inside Backend Container..."
        # Execute the pipeline inside the container
        docker-compose exec -T backend python scripts/full_pipeline.py "/app/Takeout/$FILENAME"
        
        if [ $? -eq 0 ]; then
            echo "✅ Data initialization complete!"
        else
            echo "❌ Data import failed."
        fi
    fi
else
    echo "ℹ️  No Mbox file provided. Skipping import."
    echo "   To import data later, put mbox in ./Takeout/ and run:"
    echo "   docker-compose exec backend python scripts/full_pipeline.py /app/Takeout/filename.mbox"
fi

echo ""
echo "🎉 Setup Finished!"
echo "   - Frontend: http://localhost:3000"
echo "   - Backend:  http://localhost:8000"
echo "   - API Docs: http://localhost:8000/docs"
echo ""
