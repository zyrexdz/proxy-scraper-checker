#!/usr/bin/env bash
# Zyre Proxy Scraper & Checker — Linux / macOS / WSL setup
set -e

if ! command -v python3 &> /dev/null; then
    echo "Python 3 not found. Install it via:"
    echo "  Ubuntu/Debian: sudo apt install python3 python3-pip python3-venv"
    echo "  Fedora:        sudo dnf install python3 python3-pip"
    echo "  macOS:         brew install python3"
    exit 1
fi

PYTHON_BIN="${PYTHON_BIN:-python3}"

# Create a venv unless one already exists.
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    "$PYTHON_BIN" -m venv venv
fi

# shellcheck disable=SC1091
source venv/bin/activate

echo "Upgrading pip..."
pip install -q --upgrade pip

echo "Installing dependencies..."
pip install -q -r requirements.txt

echo ""
echo "Setup complete. Run the scraper with:"
echo "  python main.py"
echo "  # or:"
echo "  python3 main.py --non-interactive"
echo ""
