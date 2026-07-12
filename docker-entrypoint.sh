#!/bin/bash
# Entrypoint script for BAS Assistant Docker container

set -e

echo "🚀 Starting BAS Assistant..."

# Load demo project if it doesn't exist
if [ ! -f "/app/data/projects/demo-hvac-project/project.json" ]; then
    echo "📦 Loading demo project..."
    python /app/scripts/load_demo.py
else
    echo "✅ Demo project already exists"
fi

# Start the application
exec "$@"