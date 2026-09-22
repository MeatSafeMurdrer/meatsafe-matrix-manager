#!/bin/bash

# Navigate to the directory where this .command file is located
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR"

# Check if the virtual environment exists. If not, build it.
if [ ! -d "venv" ]; then
    echo "First-time setup: Creating Python virtual environment..."
    python3 -m venv venv
    source venv/bin/activate
    echo "Installing dependencies..."
    pip install -r requirements.txt
    echo "Setup complete!"
    sleep 2
else
    # If it already exists, just activate it
    source venv/bin/activate
fi

# Launch the Matrix Manager
python draw_matrix_interactive.py

