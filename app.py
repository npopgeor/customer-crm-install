
# IMPORTS
from extensions import db
from sqlalchemy.exc import OperationalError
from sqlalchemy import text
import threading
import time

import os
from datetime import datetime

from flask import (
    Flask,
    request,
)

from config import (
    DATABASE_PATH,
    LOGO_UPLOAD_FOLDER,
    UPLOAD_FOLDER,
    BACKUP_LOCAL_DIR,
)

from utils import (
    daily_backup_if_needed,
    get_latest_local_backup,
    logger,
)



app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "fallback_dev_secret")

# STEP 2: Try primary DB, fallback to local if needed
fallback_db_path = get_latest_local_backup()

# === Initialize Flask App ===

try:
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{DATABASE_PATH}"
    db.init_app(app)
    with app.app_context():
        db.session.execute(text("SELECT 1"))  # trigger test query
    app.config["OFFLINE_MODE"] = False
    print("✅ Connected to OneDrive database.")

except OperationalError:
    print("❌ OneDrive DB unavailable. Switching to offline mode.")
    if fallback_db_path:
        app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{fallback_db_path}?mode=ro"
        db.init_app(app)
        app.config["OFFLINE_MODE"] = True
        print(f"🛡️ Using fallback DB: {fallback_db_path}")
    else:
        raise RuntimeError("❌ No local fallback DB found. Cannot continue.")

# Set other config values — not DB-dependent
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["LOGO_UPLOAD_FOLDER"] = LOGO_UPLOAD_FOLDER

from routes import *

from flask import g

@app.before_request
def maybe_run_daily_backup():
    if request.endpoint == "dashboard" and not getattr(g, "backup_checked", False):
        g.backup_checked = True  # Avoid running multiple times in one request cycle
        daily_backup_if_needed()





@app.template_filter("datetimeformat")
def datetimeformat(value, format="%Y-%m-%d %H:%M"):
    if isinstance(value, str):
        value = datetime.strptime(value, "%Y-%m-%dT%H:%M")
    return value.strftime(format)



# --------------------- MAIN ---------------------
def heartbeat():
    print("🫀 Heartbeat thread started.")
    logger.info("🫀 Heartbeat thread initialized.")

    while True:
        time.sleep(60)
        try:
            with app.app_context():
                db.session.execute(text("SELECT 1"))
            if app.config.get("OFFLINE_MODE"):
                logger.info("🌐 OneDrive DB appears reachable again.")
        except Exception as e:
            logger.warning(f"💤 Lost connection to OneDrive DB. App still online, but edits may fail. Reason: {e}")

# Start heartbeat thread
threading.Thread(target=heartbeat, daemon=True).start()


if __name__ == "__main__":
    ENABLE_FAKE_DATA = False  # ← Set to True if you ever want to load dummy data again

    with app.app_context():
        db.create_all()
    logger.info(f"🚦 OFFLINE_MODE = {app.config['OFFLINE_MODE']}")
    app.run(debug=True)
