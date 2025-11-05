#!/bin/bash

# Start the Python backend server

echo "Starting Semiformal Programming Backend..."

# Check if venv exists
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

# Activate venv
source venv/bin/activate

# Install dependencies
echo "Installing dependencies..."
pip install -r requirements.txt

# Check for .env file
if [ ! -f ".env" ]; then
    echo "Warning: .env file not found!"
    echo "Please create a .env file with your OPENAI_API_KEY"
    echo "You can copy .env.example and fill in your API key"
    exit 1
fi

# Start the server
echo "Starting FastAPI server on port 8000..."
cd backend
python main.py
