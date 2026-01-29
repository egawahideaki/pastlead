#!/bin/bash
cd "$(dirname "$0")"

# Check if already running
if pgrep -f "import_mbox.py" > /dev/null; then
    echo "⚠️  Import process is already running."
    echo "Check logs with: tail -f import.log"
    exit 1
fi

echo "🚀 Starting/Resuming import..."

# Activate Virtual Environment
source venv/bin/activate
export PYTHONPATH=$PYTHONPATH:$(pwd)/backend

# Target Mbox File
MBOX_FILE="すべてのメール（迷惑メール、ゴミ箱のメールを含む）-002.mbox"

# Run in background with nohup (unbuffered output)
# Run in background with nohup (unbuffered output)
nohup python -u backend/scripts/import_mbox_fast.py "$MBOX_FILE" >> import.log 2>&1 &

echo "✅ Started in background."
echo "📄 To monitor progress, run: tail -f import.log"
