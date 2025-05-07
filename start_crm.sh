#!/bin/bash
set -e

echo "🧪 Starting CRM app..."

# ✅ Step 1: Make sure virtualenv exists
if [ ! -d "venv" ]; then
  echo "❌ venv folder not found. Please run install_crm.sh first."
  exit 1
fi

# ✅ Step 2: Activate virtual environment
source venv/bin/activate
echo "✅ Virtual environment activated."

# ✅ Step 3: Set Flask environment variables
export FLASK_APP=app.py
export FLASK_ENV=production

# ✅ Step 4: Load .env variables safely
if [ -f .env ]; then
  echo "📦 Loading environment variables from .env..."
  set -a
  source .env
  set +a
else
  echo "⚠️  .env file not found. Proceeding without environment overrides."
fi

# ✅ Step 5: Check that app.py exists
if [ ! -f "app.py" ]; then
  echo "❌ app.py not found. Are you in the correct folder?"
  exit 1
fi

# ✅ Step 6: Prevent duplicate background instances
if pgrep -f "python3 app.py" > /dev/null; then
  echo "⚠️  CRM app is already running. Aborting duplicate start."
  exit 1
fi

# ✅ Step 7: Start Flask app in background
echo "🚀 Starting CRM app in background..."

LOG_FILE="crm_log.txt"
nohup python3 app.py > "$LOG_FILE" 2>&1 &
APP_PID=$!
sleep 2

if ps -p $APP_PID > /dev/null; then
  # Check for error in log
  if grep -i "Traceback" "$LOG_FILE" > /dev/null; then
    echo "❌ Error during startup! Here's the traceback:"
    grep -A 10 -i "Traceback" "$LOG_FILE"
    kill $APP_PID
    exit 1
  fi

  echo "✅ CRM app started successfully with PID $APP_PID. Visit: http://localhost:5000"
else
  echo "❌ CRM app failed to start. Process died immediately."
  tail -n 20 "$LOG_FILE"
  exit 1
fi
