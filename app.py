from models import (
    Contact, Partner, Customer, RecurringMeeting, Division, DivisionDocument,
    ActionItem, ActionItemUpdate, Meeting, DivisionOpportunity, DivisionTechnology,
    DivisionProject, CustomerOpportunity, CustomerTechnology, CustomerProject,
    FileIndex, HeatmapCell
)

from models import partner_customer, division_contacts, customer_contacts, division_contact, meeting_participants

from flask import Flask, render_template, request, redirect, url_for, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import joinedload

from werkzeug.utils import secure_filename
from datetime import datetime, timezone
from datetime import timedelta
from datetime import date
from dotenv import load_dotenv
import os
import re
import logging
from threading import Thread


#os.makedirs('backup', exist_ok=True)

from flask import send_file, abort
import io

from markupsafe import Markup
from icalendar import Calendar, Event

import csv

# === Initialize Flask App ===


app = Flask(__name__)
db = SQLAlchemy(app)


from flask import g

@app.before_request
def maybe_run_daily_backup():
    if request.endpoint == 'dashboard' and not getattr(g, 'backup_checked', False):
        g.backup_checked = True  # Avoid running multiple times in one request cycle
        daily_backup_if_needed()

# === Load Environment ===
load_dotenv()

DEVICE_NAME = os.environ.get("DEVICE_NAME", "UNKNOWN_DEVICE")

ONEDRIVE_PATH = os.environ.get("ONEDRIVE_PATH")
DATABASE_PATH = os.environ.get("DATABASE_PATH")

if not ONEDRIVE_PATH or not DATABASE_PATH:
    raise RuntimeError("❌ Missing ONEDRIVE_PATH or DATABASE_PATH in .env.")

print(f"📁 ONEDRIVE path: {ONEDRIVE_PATH}")
print(f"🗃️ DATABASE path: {DATABASE_PATH}")

SKIP_FOLDERS = {"APP", "APP backup"}
DISCOVERY_ROOT = ONEDRIVE_PATH
BACKUP_SHARED_DIR = os.path.join(ONEDRIVE_PATH, "APP backup")
BACKUP_LOCAL_DIR = os.path.join(os.getcwd(), "instance", "backup")
UPLOAD_FOLDER = os.path.join(os.getcwd(), "uploads")
LOGO_UPLOAD_FOLDER = os.path.join(app.root_path, "static", "logos")

os.makedirs(LOGO_UPLOAD_FOLDER, exist_ok=True)
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(BACKUP_LOCAL_DIR, exist_ok=True)

app.config['SQLALCHEMY_DATABASE_URI'] = f"sqlite:///{DATABASE_PATH}"
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['LOGO_UPLOAD_FOLDER'] = LOGO_UPLOAD_FOLDER

CHANGE_LOG_FILE = os.path.join(os.environ.get("ONEDRIVE_PATH", "."), "APP", "change_log.txt")
logging.basicConfig(
    filename=CHANGE_LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s — %(message)s",
)

def log_change(action: str, target: str):
    logging.info(f"[{DEVICE_NAME}] {action} → {target}")


COLUMNS = [
    "Enterprise Switching", "Internet Infra", "DC Networking",
    "Enterprise Routing", "Security", "Wireless", "Compute",
    "Assurance", "Collab", "IOT", "Meraki"
]

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

def secure_folder_name(name):
    return "".join(c for c in name if c.isalnum() or c in (' ', '_', '-')).rstrip().replace(' ', '_')


def get_customer_attachments(customer_id):
    # Find the root division (no parent)
    root = Division.query.filter_by(customer_id=customer_id, parent_id=None).first()
    if not root:
        return [], []  # No root division = no documents

    # Root documents = documents directly under root division
    root_docs = DivisionDocument.query.filter_by(division_id=root.id).all()

    # Division documents = documents under child divisions
    child_divisions = Division.query.filter_by(customer_id=customer_id).filter(Division.parent_id == root.id).all()
    child_division_ids = [d.id for d in child_divisions]

    if child_division_ids:
        division_docs = DivisionDocument.query.filter(DivisionDocument.division_id.in_(child_division_ids)).all()
    else:
        division_docs = []

    return root_docs, division_docs



@app.template_filter('datetimeformat')
def datetimeformat(value, format='%Y-%m-%d %H:%M'):
    if isinstance(value, str):
        value = datetime.strptime(value, '%Y-%m-%dT%H:%M')
    return value.strftime(format)

# --------------------- FUNCTIONS ---------------------
def sync_all_files_logic():
    customers = Customer.query.all()

    # ➕ General folder sync
    general_folder = os.path.join(app.config['UPLOAD_FOLDER'], 'General')
    os.makedirs(general_folder, exist_ok=True)

    general_div = Division.query.filter_by(name='General', customer_id=None).first()
    if not general_div:
        general_div = Division(name='General', customer_id=None)
        db.session.add(general_div)
        db.session.commit()

    general_files = []
    for root, _, files in os.walk(general_folder):
        for file in files:
            rel_path = os.path.relpath(os.path.join(root, file), app.config['UPLOAD_FOLDER'])
            if not rel_path.endswith('.DS_Store'):
                general_files.append(rel_path)

    db_general_docs = DivisionDocument.query.filter_by(division_id=general_div.id).all()
    db_general_filenames = {doc.filename for doc in db_general_docs}

    for doc in db_general_docs:
        if doc.filename not in general_files:
            db.session.delete(doc)

    for rel_path in general_files:
        if rel_path not in db_general_filenames:
            db.session.add(DivisionDocument(division_id=general_div.id, filename=rel_path))

    # 🔁 Customer folders
    for customer in customers:
        folder_name = secure_folder_name(customer.name)
        customer_folder = os.path.join(app.config['UPLOAD_FOLDER'], folder_name)
        os.makedirs(customer_folder, exist_ok=True)

        root_div = Division.query.filter_by(customer_id=customer.id, parent_id=None).first()
        if not root_div:
            root_div = Division(name=customer.name, customer_id=customer.id)
            db.session.add(root_div)
            db.session.commit()

        disk_files = []
        for root, _, files in os.walk(customer_folder):
            for file in files:
                rel_path = os.path.relpath(os.path.join(root, file), app.config['UPLOAD_FOLDER'])
                if not rel_path.endswith('.DS_Store'):
                    disk_files.append(rel_path)

        db_docs = DivisionDocument.query.filter_by(division_id=root_div.id).all()
        db_filenames = {doc.filename for doc in db_docs}

        for doc in db_docs:
            if doc.filename not in disk_files:
                db.session.delete(doc)

        for rel_path in disk_files:
            if rel_path not in db_filenames:
                db.session.add(DivisionDocument(division_id=root_div.id, filename=rel_path))

    db.session.commit()


def sync_customer_files_logic(customer_id):
    customer = Customer.query.get_or_404(customer_id)
    folder_name = secure_folder_name(customer.name)
    customer_folder = os.path.join(app.config['UPLOAD_FOLDER'], folder_name)
    os.makedirs(customer_folder, exist_ok=True)

    root_division = Division.query.filter_by(customer_id=customer.id, parent_id=None).first()
    if not root_division:
        root_division = Division(name=customer.name, customer_id=customer.id)
        db.session.add(root_division)
        db.session.commit()

    # Files on disk
    disk_files = []
    for root, _, files in os.walk(customer_folder):
        for file in files:
            full_path = os.path.join(root, file)
            rel_path = os.path.relpath(full_path, app.config['UPLOAD_FOLDER'])
            if not rel_path.endswith('.DS_Store'):
                disk_files.append(rel_path)

    # Files in DB
    db_docs = DivisionDocument.query.filter_by(division_id=root_division.id).all()
    db_filenames = {doc.filename for doc in db_docs}

    # ✅ Add this block back to remove DB records for deleted files:
    for doc in db_docs:
        if doc.filename not in disk_files:
            db.session.delete(doc)

    # Add missing ones to DB
    for rel_path in disk_files:
        if rel_path not in db_filenames:
            db.session.add(DivisionDocument(division_id=root_division.id, filename=rel_path))

    db.session.commit()

    # Optional: Clean up empty folders and stray .DS_Store
    for root, dirs, _ in os.walk(customer_folder, topdown=False):
        for d in dirs:
            folder_path = os.path.join(root, d)
            try:
                ds_store = os.path.join(folder_path, '.DS_Store')
                if os.path.isfile(ds_store):
                    os.remove(ds_store)
                if not any(os.scandir(folder_path)):
                    os.rmdir(folder_path)
            except Exception as e:
                print(f"⚠️ Could not clean {folder_path}: {e}")


def scan_and_index_files():
    FileIndex.query.delete()  # optional: clean old entries
    for root, _, files in os.walk(DISCOVERY_ROOT):
        if any(skip in root for skip in SKIP_FOLDERS):
            continue
        for file in files:
            if file.startswith('.'):
                continue
            rel_path = os.path.relpath(os.path.join(root, file), DISCOVERY_ROOT)
            parent = os.path.basename(os.path.dirname(os.path.join(root, file)))
            db.session.add(FileIndex(
                relative_path=rel_path,
                filename=file,
                parent_folder=parent
            ))
    db.session.commit()



# --------------------- MAIN ---------------------
if __name__ == '__main__':
    ENABLE_FAKE_DATA = False  # ← Set to True if you ever want to load dummy data again

    with app.app_context():
        db.create_all()

    app.run(debug=True)
