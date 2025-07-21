#!/bin/bash
set -e

echo "Starting YouTube Video Analyzer Backend..."

# Start the scheduler in daemon mode (background)
echo "Starting scheduler daemon..."
python scheduler.py --daemon &
SCHEDULER_PID=$!

# Wait a moment to ensure scheduler starts properly
sleep 2

# Check if scheduler is still running
if ! kill -0 $SCHEDULER_PID 2>/dev/null; then
    echo "ERROR: Scheduler failed to start"
    exit 1
fi

echo "Scheduler daemon started successfully (PID: $SCHEDULER_PID)"

# Start the FastAPI server in foreground
echo "Starting FastAPI server..."
exec uvicorn main:app --host 0.0.0.0 --port 8000