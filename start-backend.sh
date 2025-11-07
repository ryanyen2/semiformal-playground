#!/bin/bash

# Start the IR-based backend server (NEW default)

echo "Starting Semiformal Programming Backend (IR-based)..."

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
    echo ""
    echo "Example:"
    echo "  echo 'OPENAI_API_KEY=your-key-here' > .env"
    echo ""
    echo "Continuing without API key (parsing will work, generation will fail)..."
fi

# Start the NEW IR-based server
echo ""
echo "🚀 Starting IR-based backend server on http://localhost:8000"
echo "   Features:"
echo "   - AST-based parsing with dependency analysis"
echo "   - Shared IR with lens mechanisms"
echo "   - Unified-diff code generation"
echo "   - WebSocket support for real-time sync"
echo ""
echo "   Note: This is the NEW IR-based backend."
echo "   For the old backend, use: ./start-backend-legacy.sh"
echo ""

cd backend
python main.py
