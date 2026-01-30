#!/bin/bash
set -e

# Configuration
REPO_URL="https://github.com/egawahideaki/pastlead.git"
INSTALL_DIR="$(pwd)/pastlead"
CURRENT_DIR=$(pwd)

echo "🔮 PastLead Installer"
echo "======================"

# 1. Check Docker
if ! command -v docker &> /dev/null; then
    echo "❌ Error: Docker is not detected."
    echo "   Please install Docker Desktop first: https://www.docker.com/products/docker-desktop"
    exit 1
fi

if ! docker info &> /dev/null; then
    echo "❌ Error: Docker is installed but not running."
    echo "   Please start Docker Desktop and try again."
    exit 1
fi

# 2. Search for Mbox in current directory
echo "🔍 Searching for .mbox file in current directory..."
MBOX_FILE=$(find "$CURRENT_DIR" -maxdepth 1 -name "*.mbox" | head -n 1)

if [ -n "$MBOX_FILE" ]; then
    echo "📦 Found mail data: $(basename "$MBOX_FILE")"
else
    echo "ℹ️  No .mbox file found here."
    echo "   (The app will start empty. You can import data later.)"
fi

# 3. Setup Application
echo "⬇️  Setting up application at $INSTALL_DIR..."

if [ -d "$INSTALL_DIR" ]; then
    if [ -d "$INSTALL_DIR/.git" ]; then
        echo "   Updating existing installation..."
        cd "$INSTALL_DIR" || exit
        # Stash local changes if any to avoid conflict
        git stash > /dev/null 2>&1 || true
        git pull
    else
        echo "⚠️  Corrupted installation detected. Cleaning up..."
        rm -rf "$INSTALL_DIR"
        echo "   Cloning repository..."
        git clone --depth 1 "$REPO_URL" "$INSTALL_DIR"
        cd "$INSTALL_DIR" || exit
    fi
else
    echo "   Cloning repository..."
    git clone --depth 1 "$REPO_URL" "$INSTALL_DIR"
    cd "$INSTALL_DIR" || exit
fi

# 4. Handover to internal setup script
# We pass the absolute path of the found mbox file
if [ -n "$MBOX_FILE" ]; then
    chmod +x setup.sh
    ./setup.sh "$MBOX_FILE"
else
    chmod +x setup.sh
    ./setup.sh
fi
