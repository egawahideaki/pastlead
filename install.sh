#!/bin/bash
set -e

# Configuration
REPO_USER="egawahideaki"
REPO_NAME="pastlead"
BRANCH="main"
INSTALL_DIR="$HOME/pastlead"
ZIP_URL="https://github.com/$REPO_USER/$REPO_NAME/archive/refs/heads/$BRANCH.zip"

echo "🔮 PastLead Installer"
echo "======================"

# 0. Environment Check
OS="$(uname -s)"
if [ "$OS" != "Darwin" ]; then
    echo "⚠️  Warning: This script is optimized for macOS."
fi

# 1. Check Docker
if ! command -v docker &> /dev/null; then
    echo "❌ Error: Docker is not detected."
    echo "   Please install Docker Desktop first and try again."
    if [ "$OS" = "Darwin" ]; then
        open "https://www.docker.com/products/docker-desktop"
    fi
    exit 1
fi

if ! docker info &> /dev/null; then
    echo "❌ Error: Docker is installed but not running."
    echo "   Please start Docker Desktop."
    if [ "$OS" = "Darwin" ]; then
        open -a "Docker" || echo "   (Could not auto-start Docker)"
    fi
    exit 1
fi

# 2. Search for Mbox (User-friendly mode)
echo "🔍 Searching for mail data (.mbox)..."

MBOX_CANDIDATE=""
# Check common locations
LOCATIONS=(
    "$PWD"
    "$HOME/Downloads"
    "$HOME/Desktop"
    "$HOME/Documents"
)

set +e # Don't exit on find errors (e.g. Permission denied)
for loc in "${LOCATIONS[@]}"; do
    if [ -d "$loc" ]; then
        echo "   Checking $loc..."
        # Find first mbox file. Use || true to prevent exit on error return code.
        FOUND=$(find "$loc" -maxdepth 2 -name "*.mbox" -print -quit 2>/dev/null || true)
        if [ -n "$FOUND" ]; then
            MBOX_CANDIDATE="$FOUND"
            break
        fi
    fi
done
set -e

if [ -n "$MBOX_CANDIDATE" ]; then
    echo "📦 Found mail data: $MBOX_CANDIDATE"
else
    echo "ℹ️  No .mbox file found in Downloads, Desktop, or Documents."
    echo "   (The app will start with empty data.)"
fi


# 3. Setup Application Code
echo "⬇️  Installing PastLead to $INSTALL_DIR..."

if [ -d "$INSTALL_DIR" ]; then
    echo "   Update: Removing old installation..."
    # Backup .env if exists? Currently we overwrite logic implies clean install.
    # But let's be safe. If we want persistence, we should keep postgres_data volume.
    # This script assumes code update.
    rm -rf "$INSTALL_DIR"
fi

mkdir -p "$INSTALL_DIR"

if command -v git &> /dev/null; then
    echo "   Cloning via Git..."
    git clone --depth 1 "https://github.com/$REPO_USER/$REPO_NAME.git" "$INSTALL_DIR"
else
    echo "   Downloading via HTTP (Git not found)..."
    curl -L -o "$INSTALL_DIR/source.zip" "$ZIP_URL"
    unzip -q "$INSTALL_DIR/source.zip" -d "$INSTALL_DIR"
    # Move files from subdirectory (pastlead-main) to install dir
    mv "$INSTALL_DIR/$REPO_NAME-$BRANCH"/* "$INSTALL_DIR/"
    rm -r "$INSTALL_DIR/$REPO_NAME-$BRANCH"
    rm "$INSTALL_DIR/source.zip"
fi

# 4. Launch
cd "$INSTALL_DIR"

# Pass the found mbox file to setup.sh
chmod +x setup.sh
if [ -n "$MBOX_CANDIDATE" ]; then
    ./setup.sh "$MBOX_CANDIDATE"
else
    ./setup.sh
fi

# 5. Open Browser
echo "🎉 Setup Complete!"
echo "   Opening application..."
sleep 2
if [ "$OS" = "Darwin" ]; then
    open "http://localhost:3000"
fi
