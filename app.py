import csv
import io
import os
import re
from datetime import date, datetime, timedelta, timezone
from threading import Thread

from flask import (
    Flask,
    abort,
    redirect,
    render_template,
    request,
    send_file,
    send_from_directory,
    url_for,
)
from icalendar import Calendar, Event
from markupsafe import Markup
from werkzeug.utils import secure_filename

from config import (
    BACKUP_LOCAL_DIR,
    BACKUP_SHARED_DIR,
    CHANGE_LOG_FILE,
    COLUMNS,
    DATABASE_PATH,
    DEVICE_NAME,
    DISCOVERY_ROOT,
    LOGO_UPLOAD_FOLDER,
    ONEDRIVE_PATH,
    SKIP_FOLDERS,
    SQLALCHEMY_DATABASE_URI,
    SQLALCHEMY_TRACK_MODIFICATIONS,
    UPLOAD_FOLDER,
)
from extensions import db
from models import (
    ActionItem,
    ActionItemUpdate,
    Contact,
    Customer,
    CustomerOpportunity,
    CustomerProject,
    CustomerTechnology,
    Division,
    DivisionDocument,
    DivisionOpportunity,
    DivisionProject,
    DivisionTechnology,
    FileIndex,
    HeatmapCell,
    Meeting,
    Partner,
    RecurringMeeting,
    customer_contacts,
    division_contact,
    division_contacts,
    meeting_participants,
    partner_customer,
)
from utils import (
    log_change,
    scan_and_index_files,
    sync_all_files_logic,
    sync_customer_files_logic,
)

app = Flask(__name__)

# === Initialize Flask App ===

app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{DATABASE_PATH}"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["LOGO_UPLOAD_FOLDER"] = LOGO_UPLOAD_FOLDER

db.init_app(app)

from flask import g


@app.before_request
def maybe_run_daily_backup():
    if request.endpoint == "dashboard" and not getattr(g, "backup_checked", False):
        g.backup_checked = True  # Avoid running multiple times in one request cycle
        daily_backup_if_needed()


from routes import *


def daily_backup_if_needed():
    today = datetime.now().strftime("%Y%m%d")
    files = os.listdir(BACKUP_SHARED_DIR)
    found = any(f.startswith(f"account_team_{today}") for f in files)

    if not found:
        Thread(target=backup_db_internal).start()


def backup_db_internal():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"account_team_{timestamp}.db"

    shared_backup_path = os.path.join(BACKUP_SHARED_DIR, filename)
    local_backup_path = os.path.join(BACKUP_LOCAL_DIR, filename)

    try:
        os.makedirs(BACKUP_SHARED_DIR, exist_ok=True)
        os.makedirs(BACKUP_LOCAL_DIR, exist_ok=True)

        with open(DATABASE_PATH, "rb") as src:
            data = src.read()

        with open(shared_backup_path, "wb") as f1:
            f1.write(data)
        with open(local_backup_path, "wb") as f2:
            f2.write(data)

        print(f"✅ Backup successful: {filename}")
        log_change("Backup created", f"{filename}")

    except Exception as e:
        print(f"❌ Backup failed: {e}")


@app.template_filter("datetimeformat")
def datetimeformat(value, format="%Y-%m-%d %H:%M"):
    if isinstance(value, str):
        value = datetime.strptime(value, "%Y-%m-%dT%H:%M")
    return value.strftime(format)


# --------------------- MAIN ---------------------
if __name__ == "__main__":
    ENABLE_FAKE_DATA = False  # ← Set to True if you ever want to load dummy data again

    with app.app_context():
        db.create_all()

    app.run(debug=True)
