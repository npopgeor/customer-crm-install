#!/bin/bash
set -e

echo "🔍 Step 1: Checking for Python 3..."

if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 not found. Installing via Homebrew..."

    if ! command -v brew &> /dev/null; then
        echo "🔧 Homebrew not found. Installing..."
        /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    fi

    echo "📦 Installing Python 3..."
    brew install python
else
    echo "✅ Python 3 is installed."
fi

echo "⚙️  Step 2: Upgrading pip..."
python3 -m ensurepip --upgrade
python3 -m pip install --upgrade pip

echo "📁 Step 3: Locating OneDrive folder..."

FOLDER_NAME="Gary Bedol (gbedol)'s files - SP Accounts FY25"
SEARCH_LOCATIONS=( "$HOME/OneDrive"* "$HOME/Library/CloudStorage/" )
ONEDRIVE_PATH=""

for loc in "${SEARCH_LOCATIONS[@]}"; do
  CANDIDATE="$loc/$FOLDER_NAME"
  if [ -d "$CANDIDATE" ]; then
    ONEDRIVE_PATH="$CANDIDATE"
    break
  fi
done

if [ -z "$ONEDRIVE_PATH" ]; then
  echo "❌ Could not find '$FOLDER_NAME' in known locations."
  exit 1
fi

echo "✅ Found OneDrive path: $ONEDRIVE_PATH"

echo "🐍 Step 4: Creating virtual environment..."

if [ -d "venv" ]; then
    echo "⚠️  'venv' already exists. Removing it to start fresh..."
    rm -rf venv
fi

if ! python3 -m venv venv; then
    echo "❌ Failed to create virtual environment. Exiting..."
    exit 1
fi

echo "✅ Virtual environment created."

echo "📦 Step 5: Installing Python dependencies..."
source venv/bin/activate
pip install -r requirements.txt

echo "📂 Step 6: Creating folders..."
mkdir -p instance/backup uploads

echo "📄 Step 7: Writing environment file..."
printf 'ONEDRIVE_PATH="%s"\n' "$ONEDRIVE_PATH" > .env
printf 'DATABASE_PATH="%s/APP/account_team.db"\n' "$ONEDRIVE_PATH" >> .env


echo "🎉 Installation complete!"
echo "👉 You can now run: ./start_crm.sh"

