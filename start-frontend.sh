#!/bin/bash

# Start the IR-based frontend development server (NEW default)

echo "Starting Semiformal Programming Frontend (IR-based)..."

cd frontend

# Check if node_modules exists
if [ ! -d "node_modules" ]; then
    echo "Installing dependencies..."
    npm install
fi

# Start the NEW IR-based dev server
echo ""
echo "🚀 Starting IR-based frontend on http://localhost:5173"
echo "   Features:"
echo "   - Automatic parsing (no parse button)"
echo "   - Save-triggered generation (Cmd+S / Ctrl+S)"
echo "   - Real-time decorations and feedback"
echo "   - No manual buttons - fully automatic workflow!"
echo ""
echo "   Note: This is the NEW IR-based frontend."
echo "   For the old frontend, use: ./start-frontend-legacy.sh"
echo ""
echo "Opening browser at: http://localhost:5173/index.html"

npm run dev -- --open /index.html
