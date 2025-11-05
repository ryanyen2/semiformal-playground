#!/bin/bash

# Start the frontend development server

echo "Starting Semiformal Programming Frontend..."

cd frontend

# Check if node_modules exists
if [ ! -d "node_modules" ]; then
    echo "Installing dependencies..."
    npm install
fi

# Start the dev server
echo "Starting Vite dev server on port 3000..."
npm run dev
