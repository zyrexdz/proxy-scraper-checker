#!/usr/bin/env bash
set -e

if ! command -v python3 &> /dev/null; then
    echo "Python 3 not found in PATH."
    exit 1
fi

if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

echo "Activating virtual environment..."
source venv/bin/activate

echo "Installing dependencies..."
pip install -q --upgrade pip
pip install -q -r requirements.txt

echo "Starting scraper..."
python3 main.py
