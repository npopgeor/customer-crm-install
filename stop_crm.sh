#!/bin/bash
set -e

echo "🛑 Stopping CRM app..."

# Find the actual process running app.py regardless of Python invocation path
PIDS=$(ps aux | grep '[P]ython.*app.py' | awk '{print $2}')

if [ -z "$PIDS" ]; then
  echo "✅ No running CRM app found."
else
  echo "🔪 Killing CRM process ID(s): $PIDS"
  kill $PIDS
  echo "✅ CRM app stopped."
fi
