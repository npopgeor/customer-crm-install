#!/bin/bash

echo "🛑 Stopping CRM Python process..."

# Step 1: Kill app.py processes
PIDS=$(pgrep -f "app.py" || true)
if [ -n "$PIDS" ]; then
  echo "🔪 Killing app.py processes: $PIDS"
  kill $PIDS
else
  echo "✅ No app.py process found."
fi

# Step 2: Kill flask processes
FLASK_PIDS=$(pgrep -f "flask run" || true)
if [ -n "$FLASK_PIDS" ]; then
  echo "🔪 Killing flask processes: $FLASK_PIDS"
  kill $FLASK_PIDS
else
  echo "✅ No flask process found."
fi

# Step 3: Check virtualenv status
if [[ -n "$VIRTUAL_ENV" ]]; then
  echo "⚠️  You're currently inside the virtual environment ($VIRTUAL_ENV)"
  echo "❌ Please run 'deactivate' and re-run this script."
  exit 1
fi

# Step 4: Remove virtual environment
if [ -d "venv" ]; then
  echo "🧹 Removing virtual environment..."
  rm -rf venv || {
    echo "❌ Failed to remove venv. Trying with sudo..."
    sudo rm -rf venv
  }

  if [ -d "venv" ]; then
    echo "❌ venv folder still exists. Please delete it manually: $(pwd)/venv"
  else
    echo "✅ venv folder removed."
  fi
else
  echo "✅ No venv folder found."
fi

# Step 5: Clean other files
echo "🧹 Deleting .env file..."
rm -f .env

echo "🧹 Cleaning up logs and cache..."
rm -f crm_log.txt
find . -name "*.pyc" -delete
find . -name "__pycache__" -type d -exec rm -r {} +

echo "🎉 Uninstall complete."

