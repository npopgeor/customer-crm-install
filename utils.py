import logging
from logging.handlers import RotatingFileHandler
import os
from threading import Thread
from datetime import datetime
from flask import session

import time
import getpass

from config import (
    DISCOVERY_ROOT,
    SKIP_FOLDERS,
    UPLOAD_FOLDER,
    ONEDRIVE_PATH,
    BACKUP_SHARED_DIR,
    BACKUP_LOCAL_DIR,
    DATABASE_PATH,
    LOCK_FILE,

)
from extensions import db
from models import Customer, Division, DivisionDocument, FileIndex


# --------------------- FUNCTIONS ---------------------

def secure_folder_name(name):
    return (
        "".join(c for c in name if c.isalnum() or c in (" ", "_", "-"))
        .rstrip()
        .replace(" ", "_")
    )


def get_customer_attachments(customer_id):
    # Find the root division (no parent)
    root = Division.query.filter_by(customer_id=customer_id, parent_id=None).first()
    if not root:
        return [], []  # No root division = no documents

    # Root documents = documents directly under root division
    root_docs = DivisionDocument.query.filter_by(division_id=root.id).all()

    # Division documents = documents under child divisions
    child_divisions = (
        Division.query.filter_by(customer_id=customer_id)
        .filter(Division.parent_id == root.id)
        .all()
    )
    child_division_ids = [d.id for d in child_divisions]

    if child_division_ids:
        division_docs = DivisionDocument.query.filter(
            DivisionDocument.division_id.in_(child_division_ids)
        ).all()
    else:
        division_docs = []

    return root_docs, division_docs


def sync_all_files_logic():
    customers = Customer.query.all()

    # ➕ General folder sync
    general_folder = os.path.join(UPLOAD_FOLDER, "General")
    os.makedirs(general_folder, exist_ok=True)

    general_div = Division.query.filter_by(name="General", customer_id=None).first()
    if not general_div:
        general_div = Division(name="General", customer_id=None)
        db.session.add(general_div)
        db.session.commit()

    general_files = []
    for root, _, files in os.walk(general_folder):
        for file in files:
            rel_path = os.path.relpath(os.path.join(root, file), UPLOAD_FOLDER)
            if not rel_path.endswith(".DS_Store"):
                general_files.append(rel_path)

    db_general_docs = DivisionDocument.query.filter_by(division_id=general_div.id).all()
    db_general_filenames = {doc.filename for doc in db_general_docs}

    for doc in db_general_docs:
        if doc.filename not in general_files:
            db.session.delete(doc)

    for rel_path in general_files:
        if rel_path not in db_general_filenames:
            db.session.add(
                DivisionDocument(division_id=general_div.id, filename=rel_path)
            )

    # 🔁 Customer folders
    for customer in customers:
        folder_name = secure_folder_name(customer.name)
        customer_folder = os.path.join(UPLOAD_FOLDER, folder_name)
        os.makedirs(customer_folder, exist_ok=True)

        root_div = Division.query.filter_by(
            customer_id=customer.id, parent_id=None
        ).first()
        if not root_div:
            root_div = Division(name=customer.name, customer_id=customer.id)
            db.session.add(root_div)
            db.session.commit()

        disk_files = []
        for root, _, files in os.walk(customer_folder):
            for file in files:
                rel_path = os.path.relpath(os.path.join(root, file), UPLOAD_FOLDER)
                if not rel_path.endswith(".DS_Store"):
                    disk_files.append(rel_path)

        db_docs = DivisionDocument.query.filter_by(division_id=root_div.id).all()
        db_filenames = {doc.filename for doc in db_docs}

        for doc in db_docs:
            if doc.filename not in disk_files:
                db.session.delete(doc)

        for rel_path in disk_files:
            if rel_path not in db_filenames:
                db.session.add(
                    DivisionDocument(division_id=root_div.id, filename=rel_path)
                )

    db.session.commit()


def sync_customer_files_logic(customer_id):
    customer = Customer.query.get_or_404(customer_id)
    folder_name = secure_folder_name(customer.name)
    customer_folder = os.path.join(UPLOAD_FOLDER, folder_name)
    os.makedirs(customer_folder, exist_ok=True)

    root_division = Division.query.filter_by(
        customer_id=customer.id, parent_id=None
    ).first()
    if not root_division:
        root_division = Division(name=customer.name, customer_id=customer.id)
        db.session.add(root_division)
        db.session.commit()

    # Files on disk
    disk_files = []
    for root, _, files in os.walk(customer_folder):
        for file in files:
            full_path = os.path.join(root, file)
            rel_path = os.path.relpath(full_path, UPLOAD_FOLDER)
            if not rel_path.endswith(".DS_Store"):
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
            db.session.add(
                DivisionDocument(division_id=root_division.id, filename=rel_path)
            )

    db.session.commit()

    # Optional: Clean up empty folders and stray .DS_Store
    for root, dirs, _ in os.walk(customer_folder, topdown=False):
        for d in dirs:
            folder_path = os.path.join(root, d)
            try:
                ds_store = os.path.join(folder_path, ".DS_Store")
                if os.path.isfile(ds_store):
                    os.remove(ds_store)
                if not any(os.scandir(folder_path)):
                    os.rmdir(folder_path)
            except Exception as e:
                logger.error(f"⚠️ Could not clean {folder_path}: {e}")


def scan_and_index_files():
    FileIndex.query.delete()  # optional: clean old entries
    for root, _, files in os.walk(DISCOVERY_ROOT):
        if any(skip in root for skip in SKIP_FOLDERS):
            continue
        for file in files:
            if file.startswith("."):
                continue
            rel_path = os.path.relpath(os.path.join(root, file), DISCOVERY_ROOT)
            parent = os.path.basename(os.path.dirname(os.path.join(root, file)))
            db.session.add(
                FileIndex(relative_path=rel_path, filename=file, parent_folder=parent)
            )
    db.session.commit()


def daily_backup_if_needed():
    today = datetime.now().strftime("%Y%m%d")

    if not os.path.exists(BACKUP_SHARED_DIR):
        logger.warning(f"🚫 Backup skipped — shared backup folder not accessible: {BACKUP_SHARED_DIR}")
        return

    try:
        files = os.listdir(BACKUP_SHARED_DIR)
        found = any(f.startswith(f"account_team_{today}") for f in files)

        if not found:
            logger.info("📦 No backup found for today. Starting one now...")
            Thread(target=backup_db_internal).start()
        else:
            logger.debug("✅ Daily backup already exists. No action needed.")

    except Exception as e:
        logger.warning(f"⚠️ Failed to check or create daily backup: {e}")


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

        logger.info(f"✅ Backup successful: {filename}")
        log_change("Backup created", f"{filename}")

    except Exception as e:
        logger.error(f"❌ Backup failed: {e}")


# === Check last backup ===


def get_last_backup_times():
    last_shared = None
    last_local = None

    try:
        shared_files = [
            f for f in os.listdir(BACKUP_SHARED_DIR) if f.startswith("account_team_")
        ]
        local_files = [
            f for f in os.listdir(BACKUP_LOCAL_DIR) if f.startswith("account_team_")
        ]
        if shared_files:
            shared_files.sort(reverse=True)
            last_shared = shared_files[0]

        if local_files:
            local_files.sort(reverse=True)
            last_local = local_files[0]
        def extract_dt(filename):
            try:
                # Grab the part between 'account_team_' and '.db'
                ts = filename.replace("account_team_", "").replace(".db", "")
                return datetime.strptime(ts, "%Y%m%d_%H%M%S")
            except:
                return None

        return {
            "shared": extract_dt(last_shared) if last_shared else None,
            "local": extract_dt(last_local) if last_local else None
        }

    except Exception as e:
        return {"shared": None, "local": None}


#= Logging setup ===
CHANGE_LOG_FILE = os.path.join(ONEDRIVE_PATH, "APP", "change_log.txt")
log_dir = os.path.dirname(CHANGE_LOG_FILE)

logger = logging.getLogger("crm_logger")
logger.setLevel(logging.INFO)

if os.path.exists(log_dir):
    # 📦 Rotating file handler: max ~1MB per file, keep last 5
    file_handler = RotatingFileHandler(CHANGE_LOG_FILE, maxBytes=1_000_000, backupCount=5)
    file_handler.setFormatter(logging.Formatter("%(asctime)s — %(message)s"))
    logger.addHandler(file_handler)
    logger.info("📝 File logging initialized.")
else:
    # Fallback: optionally just log to console or do nothing
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter("%(asctime)s — %(message)s"))
    logger.addHandler(console_handler)
    logger.warning(f"🚫 Logging to file skipped — OneDrive log path missing: {log_dir}")

# === Logging call ===
def log_change(action: str, target: str):
    logger.info(f"[{get_device_name()}] {action} → {target}")


# 🔒 Lock file path — make sure this is inside the shared OneDrive folder

def acquire_lock():
    if os.path.exists(LOCK_FILE):
        return False
    with open(LOCK_FILE, "w") as f:
        f.write(f"{getpass.getuser()} at {datetime.now()}")
    session["owns_lock"] = True  # ✅ Store ownership
    return True

def release_lock():
    if os.path.exists(LOCK_FILE):
        os.remove(LOCK_FILE)
    session.pop("owns_lock", None)  # ✅ Clear ownership


def is_locked():
    """
    Check if lock file exists.
    """
    return os.path.exists(LOCK_FILE)

def lock_info():
    """
    Return contents of the lock file, or None if not locked.
    """
    if not os.path.exists(LOCK_FILE):
        return None
    with open(LOCK_FILE, "r") as f:
        return f.read().strip()

def lock_expired(timeout_sec=300):
    """
    Check if the lock file is older than the timeout (default: 5 minutes).
    """
    if not os.path.exists(LOCK_FILE):
        return False
    age = time.time() - os.path.getmtime(LOCK_FILE)
    return age > timeout_sec

# ----- SCAN FILES TWICE A DAY
file_scan_cache = {
    "date": None,
    "scanned_11": False,
    "scanned_16": False,
    "count": 0
}

def get_new_files_today_count(DISCOVERY_ROOT, SKIP_FOLDERS):
    now = datetime.now()
    today = now.date()
    hour = now.hour

    # Reset at midnight
    if file_scan_cache["date"] != today:
        logger.info("🕛 New day detected. Resetting file scan cache.")
        file_scan_cache.update({
            "date": today,
            "scanned_11": False,
            "scanned_16": False,
            "count": 0
        })

    # Determine if we are in a scan window
    should_scan = False
    scan_window = None

    if 11 <= hour < 16 and not file_scan_cache["scanned_11"]:
        should_scan = True
        scan_window = "11AM"
    elif 16 <= hour <= 23 and not file_scan_cache["scanned_16"]:
        should_scan = True
        scan_window = "4PM"

    if not should_scan:
        return file_scan_cache["count"]

    # ✅ Perform scan
    try:
        count = 0
        for root, _, files in os.walk(DISCOVERY_ROOT):
            if any(skip in root for skip in SKIP_FOLDERS):
                continue
            for file in files:
                if file.startswith("."):
                    continue
                full_path = os.path.join(root, file)
                try:
                    mod_time = os.path.getmtime(full_path)
                    if datetime.fromtimestamp(mod_time).date() == today:
                        count += 1
                except FileNotFoundError:
                    continue

        file_scan_cache["count"] = count

        # ✅ Now mark the appropriate scan window as completed
        if scan_window == "11AM":
            file_scan_cache["scanned_11"] = True
        elif scan_window == "4PM":
            file_scan_cache["scanned_16"] = True

        logger.info(f"📂 File scan completed at {scan_window}: {count} new files found.")
        return count

    except Exception as e:
        logger.warning(f"⚠️ File scan failed during {scan_window or 'unknown'} window: {e}")
        return file_scan_cache["count"]  # fallback to last known value

def get_device_name():
    return session.get("username", "UNKNOWN_USER")