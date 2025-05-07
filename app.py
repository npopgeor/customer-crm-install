from models import (
    Contact, Partner, Customer, RecurringMeeting, Division, DivisionDocument,
    ActionItem, ActionItemUpdate, Meeting, DivisionOpportunity, DivisionTechnology,
    DivisionProject, CustomerOpportunity, CustomerTechnology, CustomerProject,
    FileIndex, HeatmapCell
)

from models import partner_customer, division_contacts, customer_contacts, division_contact, meeting_participants

from config import (
    DEVICE_NAME, ONEDRIVE_PATH, DATABASE_PATH,
    SKIP_FOLDERS, DISCOVERY_ROOT, BACKUP_SHARED_DIR,
    BACKUP_LOCAL_DIR, UPLOAD_FOLDER, LOGO_UPLOAD_FOLDER,
    SQLALCHEMY_DATABASE_URI, SQLALCHEMY_TRACK_MODIFICATIONS,
    COLUMNS, CHANGE_LOG_FILE
)

from utils import scan_and_index_files, sync_customer_files_logic, sync_all_files_logic, log_change

from flask import Flask, render_template, request, redirect, url_for, send_from_directory
from extensions import db
import os
from werkzeug.utils import secure_filename
from datetime import datetime, timezone
from datetime import timedelta
from datetime import date
import re
from threading import Thread

from flask import send_file, abort
import io

from markupsafe import Markup
from icalendar import Calendar, Event

import csv

app = Flask(__name__)

# === Initialize Flask App ===

app.config['SQLALCHEMY_DATABASE_URI'] = f"sqlite:///{DATABASE_PATH}"
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['LOGO_UPLOAD_FOLDER'] = LOGO_UPLOAD_FOLDER

db.init_app(app)

from flask import g

@app.before_request
def maybe_run_daily_backup():
    if request.endpoint == 'dashboard' and not getattr(g, 'backup_checked', False):
        g.backup_checked = True  # Avoid running multiple times in one request cycle
        daily_backup_if_needed()

from routes import *


def daily_backup_if_needed():
    today = datetime.now().strftime('%Y%m%d')
    files = os.listdir(BACKUP_SHARED_DIR)
    found = any(f.startswith(f"account_team_{today}") for f in files)

    if not found:
        Thread(target=backup_db_internal).start()

def backup_db_internal():
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f"account_team_{timestamp}.db"

    shared_backup_path = os.path.join(BACKUP_SHARED_DIR, filename)
    local_backup_path = os.path.join(BACKUP_LOCAL_DIR, filename)

    try:
        os.makedirs(BACKUP_SHARED_DIR, exist_ok=True)
        os.makedirs(BACKUP_LOCAL_DIR, exist_ok=True)

        with open(DATABASE_PATH, 'rb') as src:
            data = src.read()

        with open(shared_backup_path, 'wb') as f1:
            f1.write(data)
        with open(local_backup_path, 'wb') as f2:
            f2.write(data)

        print(f"✅ Backup successful: {filename}")
        log_change("Backup created", f"{filename}")

    except Exception as e:
        print(f"❌ Backup failed: {e}")



@app.template_filter('datetimeformat')
def datetimeformat(value, format='%Y-%m-%d %H:%M'):
    if isinstance(value, str):
        value = datetime.strptime(value, '%Y-%m-%dT%H:%M')
    return value.strftime(format)



# --------------------- MAIN ---------------------
if __name__ == '__main__':
    ENABLE_FAKE_DATA = False  # ← Set to True if you ever want to load dummy data again

    with app.app_context():
        db.create_all()

    app.run(debug=True)
