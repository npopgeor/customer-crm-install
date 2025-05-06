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
    "Enterprise Switching", "Internet Infrastructure", "DC Networking",
    "Enterprise Routing", "Security", "Wireless", "Compute",
    "Assurance", "Collaboration", "IOT", "Meraki"
]


db = SQLAlchemy(app)

partner_customer = db.Table('partner_customer',
    db.Column('partner_id', db.Integer, db.ForeignKey('partner.id'), primary_key=True),
    db.Column('customer_id', db.Integer, db.ForeignKey('customer.id'), primary_key=True)
)

division_contacts = db.Table('division_contacts',
    db.Column('division_id', db.Integer, db.ForeignKey('division.id')),
    db.Column('contact_id', db.Integer, db.ForeignKey('contact.id'))
)


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

# --------------------- MODELS ---------------------

class Contact(db.Model):
    __tablename__ = 'contact'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100))
    phone = db.Column(db.String(50))
    role = db.Column(db.String(100), nullable=False)
    location = db.Column(db.String(100))
    reports_to = db.Column(db.Integer, db.ForeignKey('contact.id'))
    notes = db.Column(db.Text)
    contact_type = db.Column(db.String(20))
    technology = db.Column(db.String(100))  # New field added
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'), nullable=True)
    partner_id = db.Column(db.Integer, db.ForeignKey('partner.id'), nullable=True)

    manager = db.relationship('Contact', remote_side=[id], backref='subordinates', uselist=False)
    customer = db.relationship('Customer', backref='contacts', foreign_keys=[customer_id])
    partner = db.relationship('Partner', backref='contacts', foreign_keys=[partner_id])

class Partner(db.Model):
    __tablename__ = 'partner'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    notes = db.Column(db.Text)

    customers = db.relationship('Customer', secondary=partner_customer, backref='partners')

class Customer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    cx_services = db.Column(db.Text)
    notes = db.Column(db.Text)
    
    divisions = db.relationship('Division', back_populates='customer', cascade='all, delete-orphan')
    action_items = db.relationship('ActionItem', backref='customer', lazy=True)
    meetings = db.relationship('Meeting', backref='customer', lazy=True)
    recurring_meetings = db.relationship('RecurringMeeting', back_populates='customer', lazy=True)

    # New Relationships
    opportunities = db.relationship('CustomerOpportunity', backref='customer', lazy=True, cascade='all, delete-orphan')
    technologies = db.relationship('CustomerTechnology', backref='customer', lazy=True, cascade='all, delete-orphan')
    projects = db.relationship('CustomerProject', backref='customer', lazy=True, cascade='all, delete-orphan')

    def get_enriched_recurring_meetings(self):
        enriched = []
        today = datetime.now()
        for rm in self.recurring_meetings:
            next_time = rm.get_next_occurrence(today)
            recurrence = rm.get_human_readable_recurrence()
            enriched.append({
                "title": rm.title,
                "recurrence": recurrence,
                "next": next_time.strftime('%b %d, %Y @ %I:%M %p') if next_time else "—"
            })
        return enriched

class RecurringMeeting(db.Model):
    __tablename__ = 'recurring_meeting'
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'), nullable=False)
    start_datetime = db.Column(db.DateTime, nullable=False)
    title = db.Column(db.String(200), nullable=False)
    host = db.Column(db.String(100))
    recurrence_pattern = db.Column(db.String(50))  # e.g., daily, weekly, biweekly
    repeat_until = db.Column(db.Date)
    description = db.Column(db.Text)
    generate_ics = db.Column(db.Boolean, default=False)
    duration_minutes = db.Column(db.Integer, default=60)  # ✅ Added duration field


    customer = db.relationship('Customer', back_populates='recurring_meetings')

    def get_next_occurrence(self, today=None):
        today = today or datetime.now()
        current = self.start_datetime

        if current >= today:
            return current

        while current.date() <= self.repeat_until:
                if self.recurrence_pattern == 'daily':
                    current += timedelta(days=1)
                elif self.recurrence_pattern == 'weekly':
                    current += timedelta(weeks=1)
                elif self.recurrence_pattern == 'biweekly':
                    current += timedelta(weeks=2)
                elif self.recurrence_pattern == 'monthly':
                    current += timedelta(weeks=4)  # ⬅️ NOW really means "every 4 weeks"
                else:
                    break

                if current >= today:
                    return current

        return None

    def get_human_readable_recurrence(self):
        dt = self.start_datetime
        weekday = dt.strftime('%A')
        time_str = dt.strftime('%I:%M %p').lstrip('0')

        if self.recurrence_pattern == 'daily':
            return f"Repeats daily at {time_str}"
        elif self.recurrence_pattern == 'weekly':
            return f"Repeats every {weekday} at {time_str}"
        elif self.recurrence_pattern == 'biweekly':
            return f"Repeats every other {weekday} at {time_str}"
        elif self.recurrence_pattern == 'monthly':
            return f"Repeats every 4 weeks on {weekday} at {time_str}"  # 👈 Updated description
        else:
            return f"Repeats: {self.recurrence_pattern} at {time_str}"




customer_contacts = db.Table('customer_contacts',
    db.Column('customer_id', db.Integer, db.ForeignKey('customer.id')),
    db.Column('contact_id', db.Integer, db.ForeignKey('contact.id'))
)

# Association Table (MUST be defined before usage)
division_contact = db.Table('division_contact',
    db.Column('division_id', db.Integer, db.ForeignKey('division.id'), primary_key=True),
    db.Column('contact_id', db.Integer, db.ForeignKey('contact.id'), primary_key=True)
)


class Division(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'))
    parent_id = db.Column(db.Integer, db.ForeignKey('division.id'))
    document = db.Column(db.String(200)) 

    customer = db.relationship('Customer', back_populates='divisions')
    parent = db.relationship('Division', remote_side=[id], backref='children')
    contacts = db.relationship('Contact', secondary=division_contact, backref='divisions')
    opportunities = db.relationship('DivisionOpportunity', backref='division', cascade='all, delete-orphan')
    technologies = db.relationship('DivisionTechnology', backref='division', cascade='all, delete-orphan')
    projects = db.relationship('DivisionProject', backref='division', cascade='all, delete-orphan')

class DivisionDocument(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    division_id = db.Column(db.Integer, db.ForeignKey('division.id'), nullable=False)
    filename = db.Column(db.String(200), nullable=False)
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)

    division = db.relationship('Division', backref='documents')


class ActionItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.String(20))
    detail = db.Column(db.Text, nullable=False)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'), nullable=True)
    customer_contact = db.Column(db.String(100))
    cisco_contact = db.Column(db.String(100))
    completed = db.Column(db.Boolean, default=False)
    category = db.Column(db.String(50), default='daily')  # ← NEW LINE

    updates = db.relationship(
        'ActionItemUpdate',
        back_populates='parent',
        cascade='all, delete-orphan',
        order_by='desc(ActionItemUpdate.timestamp)'
    )


meeting_participants = db.Table('meeting_participants',
    db.Column('meeting_id', db.Integer, db.ForeignKey('meeting.id')),
    db.Column('contact_id', db.Integer, db.ForeignKey('contact.id'))
)

class Meeting(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'), nullable=True)
    date = db.Column(db.String(20))
    title = db.Column(db.String(200))
    host = db.Column(db.String(100))
    notes = db.Column(db.Text)
    participants = db.relationship('Contact', secondary=meeting_participants, backref='meetings')


class DivisionOpportunity(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    division_id = db.Column(db.Integer, db.ForeignKey('division.id'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    value = db.Column(db.String(100))
    stage = db.Column(db.String(100))
    notes = db.Column(db.Text)

class DivisionTechnology(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    division_id = db.Column(db.Integer, db.ForeignKey('division.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    discount_level = db.Column(db.Integer)
    notes = db.Column(db.Text)

class DivisionProject(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    division_id = db.Column(db.Integer, db.ForeignKey('division.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    status = db.Column(db.String(100))
    owner = db.Column(db.String(100))
    notes = db.Column(db.Text)

class CustomerOpportunity(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    value = db.Column(db.String(100))
    stage = db.Column(db.String(100))
    notes = db.Column(db.Text)

class CustomerTechnology(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    discount_level = db.Column(db.Integer)
    notes = db.Column(db.Text)

class CustomerProject(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    status = db.Column(db.String(100))
    owner = db.Column(db.String(100))
    notes = db.Column(db.Text)



class ActionItemUpdate(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    action_item_id = db.Column(db.Integer, db.ForeignKey('action_item.id'), nullable=False)
    update_text = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    parent = db.relationship('ActionItem', back_populates='updates')


class FileIndex(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    relative_path = db.Column(db.String(500), unique=True, nullable=False)
    filename = db.Column(db.String(200), nullable=False)
    parent_folder = db.Column(db.String(300))
    last_indexed = db.Column(db.DateTime, default=datetime.utcnow)


class HeatmapCell(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'), nullable=False)
    column_name = db.Column(db.String(128), nullable=False)   # e.g., "Security", "Wireless"
    color = db.Column(db.String(20), nullable=True)           # e.g., "red", "yellow", "green"
    text = db.Column(db.String(255), nullable=True)           # editable cell content

    __table_args__ = (
        db.UniqueConstraint('customer_id', 'column_name', name='_customer_column_uc'),
    )


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


# --------------------- ROUTES ---------------------

@app.route('/')
def home():
    return redirect(url_for('dashboard'))

def get_grouped_contacts():
    cisco_contacts = Contact.query.filter_by(contact_type='Cisco').order_by(Contact.name).all()

    customer_groups = []
    for customer in Customer.query.order_by(Customer.name).all():
        filtered = [c for c in customer.contacts if c.contact_type == 'Customer']
        if filtered:
            customer.contacts = filtered
            customer_groups.append(customer)

    partner_groups = []
    for partner in Partner.query.order_by(Partner.name).all():
        filtered = [c for c in partner.contacts if c.contact_type == 'Partner']
        if filtered:
            partner.contacts = filtered
            partner_groups.append(partner)

    unassigned_contacts = Contact.query.filter_by(contact_type='Unassigned').order_by(Contact.name).all()

    return {
        "cisco_contacts": cisco_contacts,
        "customer_contacts": customer_groups,
        "partner_contacts": partner_groups,
        "unassigned_contacts": unassigned_contacts  # ← Add this
    }

@app.route('/search')
def search():
    query = request.args.get('q', '').strip()
    query_words = query.lower().split()  # ✅ Define early, before use

    customers = Customer.query.filter(
        (Customer.name.ilike(f"%{query}%")) |
        (Customer.cx_services.ilike(f"%{query}%")) |
        (Customer.notes.ilike(f"%{query}%"))
    ).all()

    contacts = Contact.query.filter(
        (Contact.name.ilike(f"%{query}%")) |
        (Contact.email.ilike(f"%{query}%")) |
        (Contact.role.ilike(f"%{query}%")) |
        (Contact.location.ilike(f"%{query}%")) |
        (Contact.technology.ilike(f"%{query}%")) |
        (Contact.notes.ilike(f"%{query}%")) |
        (Contact.customer.has(Customer.name.ilike(f"%{query}%")))
    ).all()

    partners = Partner.query.filter(
        (Partner.name.ilike(f"%{query}%")) |
        (Partner.notes.ilike(f"%{query}%"))
    ).all()

    file_name_hits = []

    for root, dirs, files in os.walk(DISCOVERY_ROOT):
        if any(skip in root for skip in SKIP_FOLDERS):
            continue

        rel_root = os.path.relpath(root, DISCOVERY_ROOT)
        if all(word in rel_root.lower() for word in query_words):
            file_name_hits.append(rel_root + '/')

        for file in files:
            if file.startswith('.'):
                continue
            if all(word in file.lower() for word in query_words):
                rel_path = os.path.relpath(os.path.join(root, file), DISCOVERY_ROOT)
                file_name_hits.append(rel_path)

    return render_template(
        'search_results.html',
        query=query,
        customers=customers,
        contacts=contacts,
        partners=partners,
        file_name_hits=file_name_hits
    )


from datetime import datetime

@app.route('/files')
def all_files_by_customer():
    grouped_files = {}
    all_files = []

    for root, _, files in os.walk(DISCOVERY_ROOT):
        if any(skip in root for skip in SKIP_FOLDERS):
            continue
        for file in files:
            if file.startswith('.'):
                continue
            full_path = os.path.join(root, file)
            rel_path = os.path.relpath(full_path, DISCOVERY_ROOT)
            mod_time = os.path.getmtime(full_path)
            all_files.append({
                'path': rel_path,
                'timestamp': mod_time,
                'date': datetime.fromtimestamp(mod_time).strftime('%Y-%m-%d %H:%M')
            })

            # Build tree
            parts = rel_path.split('/')
            current = grouped_files
            for part in parts[:-1]:
                current = current.setdefault(part, {})
            current[parts[-1]] = rel_path

    recent_files = sorted(all_files, key=lambda x: x['timestamp'], reverse=True)[:5]

    return render_template("all_files.html", grouped_files=grouped_files, recent_files=recent_files)

@app.route('/sync_all_files', methods=['POST'])
def sync_all_files():
    scan_and_index_files()
    return redirect(url_for('all_files_by_customer'))

@app.route('/onedrive/<path:filename>')
def serve_from_onedrive(filename):
    full_path = os.path.join(DISCOVERY_ROOT, filename)
    if not os.path.isfile(full_path):
        abort(404)
    return send_file(full_path)


@app.route('/contacts')
def contact_list():
    grouped_contacts = get_grouped_contacts()
    return render_template('contacts.html', **grouped_contacts)

@app.route('/contacts/<int:contact_id>')
def view_contact(contact_id):
    contact = Contact.query.get_or_404(contact_id)
    return render_template('view_contact.html', contact=contact)


@app.route('/contacts/add', methods=['GET', 'POST'])
def add_contact():
    if request.method == 'POST':
        c = Contact(
            name=request.form['name'],
            email=request.form['email'],
            phone=request.form.get('phone'),
            role=request.form['role'],
            location=request.form.get('location'),
            technology=request.form.get('technology'),  # 👈 Added this line
            notes=request.form.get('notes'),
            contact_type=request.form.get('contact_type'),
            reports_to=request.form.get('reports_to') or None,
            customer_id=request.form.get('customer_id') or None,
            partner_id=request.form.get('partner_id') or None
        )
        db.session.add(c)
        division_ids = request.form.getlist('division_ids')
        if division_ids:
            divisions_to_add = Division.query.filter(Division.id.in_(division_ids)).all()
            c.divisions = divisions_to_add


        db.session.commit()
        log_change("Added contact", f"{c.name} – {c.email}")
        return redirect(url_for('contact_list'))

    # 👇 Keep everything below the same
    def serialize_contact(contact):
        return {
            "id": contact.id,
            "name": contact.name,
            "customer_id": contact.customer_id
        }

    customer_grouped = {}
    all_customer_contacts = Contact.query.filter_by(contact_type='Customer').order_by(Contact.name).all()
    for c in all_customer_contacts:
        if c.customer_id:
            customer_grouped.setdefault(c.customer_id, []).append(serialize_contact(c))

    contacts_by_type = {
        'Cisco': [serialize_contact(c) for c in Contact.query.filter_by(contact_type='Cisco').order_by(Contact.name).all()],
        'Partner': [serialize_contact(c) for c in Contact.query.filter_by(contact_type='Partner').order_by(Contact.name).all()],
        'Customer': customer_grouped
    }

    customers = Customer.query.all()
    partners = Partner.query.all()

    # In your add_contact() GET section
    divisions = Division.query.order_by(Division.name).all()
    customer_div_map = {}
    for c in customers:
        customer_div_map[c.id] = [{"id": d.id, "name": d.name} for d in c.divisions if d.parent_id is not None]

    # Pass to template:
    return render_template(
        'add_contact.html',
        contacts_by_type=contacts_by_type,
        customers=customers,
        partners=partners,
        divisions=divisions,  # ✅ add this
        customer_divisions=customer_div_map
    )


@app.route('/contacts/edit/<int:contact_id>', methods=['GET', 'POST'])
def edit_contact(contact_id):
    contact = Contact.query.get_or_404(contact_id)
    customers = Customer.query.all()
    partners = Partner.query.all()
    all_contacts = Contact.query.filter(Contact.id != contact.id).all()

    if request.method == 'POST':
        contact.name = request.form['name']
        contact.email = request.form['email']
        contact.phone = request.form.get('phone')
        contact.role = request.form['role']
        contact.location = request.form.get('location')
        contact.reports_to = request.form.get('reports_to') or None
        contact.notes = request.form.get('notes')
        contact.contact_type = request.form['contact_type']
        contact.customer_id = request.form.get('customer_id') or None
        contact.partner_id = request.form.get('partner_id') or None

        # ✅ Update divisions only if contact is a customer contact
        if contact.contact_type == 'Customer' and contact.customer_id:
            division_ids = request.form.getlist('division_ids')
            contact.divisions = Division.query.filter(Division.id.in_(division_ids)).all()
        else:
            contact.divisions = []  # Clear if no customer type

        db.session.commit()
        log_change("Edited contact", f"{contact.name} – {contact.email}")
        return redirect(url_for('contact_list'))

    def serialize_contact(c):
        return {
            'id': c.id,
            'name': c.name,
            'customer_id': c.customer_id,
            'partner_id': c.partner_id
        }

    contacts_by_type = {
        'Cisco': [serialize_contact(c) for c in Contact.query.filter(Contact.id != contact.id, Contact.contact_type == 'Cisco').order_by(Contact.name).all()],
        'Customer': [serialize_contact(c) for c in Contact.query.filter(Contact.id != contact.id, Contact.contact_type == 'Customer').order_by(Contact.name).all()],
        'Partner': [serialize_contact(c) for c in Contact.query.filter(Contact.id != contact.id, Contact.contact_type == 'Partner').order_by(Contact.name).all()],
    }

    # ✅ Divisions for the contact’s customer
    customer_divisions = {
    str(c.id): [
        {"id": d.id, "name": d.name}
        for d in c.divisions if d.parent_id  # filter only real sub-divisions
    ]
    for c in customers
    }

    return render_template(
    'edit_contact.html',
    contact=contact,
    customers=customers,
    partners=partners,
    contacts_by_type=contacts_by_type,
    customer_divisions=customer_divisions,  # ✅ THIS
    )



@app.route('/contacts/delete/<int:contact_id>')
def delete_contact(contact_id):
    contact = Contact.query.get_or_404(contact_id)

    # Remove from any customer's contact list
    for customer in Customer.query.all():
        if contact in customer.contacts:
            customer.contacts.remove(contact)

    # Clear customer_id and partner_id (if present)
    contact.customer_id = None
    contact.partner_id = None

    # Disassociate from meetings
    for meeting in contact.meetings:
        meeting.participants.remove(contact)
    log_change("Deleted contact", f"{contact.name} – {contact.email}")
    db.session.delete(contact)
    db.session.commit()
    return redirect(url_for('contact_list'))


@app.route('/contacts/delete_all')
def delete_all_contacts():
    log_change("Deleted all contacts", "All contacts removed via bulk delete.")
    db.session.execute(division_contact.delete())  # Clean up many-to-many link
    Contact.query.delete()
    db.session.commit()
    return redirect(url_for('contact_list'))


@app.route('/contacts/export_csv')
def export_contacts_csv():
    from io import StringIO
    import csv

    contacts = Contact.query.all()

    si = StringIO()
    writer = csv.writer(si)
    writer.writerow([
        'name', 'email', 'phone', 'role', 'location',
        'technology', 'contact_type', 'reports_to',
        'customer_name', 'partner_name', 'division_name', 'notes'
    ])

    for c in contacts:
        # If multiple divisions exist, join them with '; '
        division_names = '; '.join([d.name for d in c.divisions]) if c.divisions else ''

        writer.writerow([
            c.name or '',
            c.email or '',
            c.phone or '',
            c.role or '',
            c.location or '',
            c.technology or '',
            c.contact_type or '',
            c.manager.name if c.manager else '',
            c.customer.name if c.customer else '',
            c.partner.name if c.partner else '',
            division_names,
            c.notes or ''
        ])

    output = io.BytesIO()
    output.write(si.getvalue().encode('utf-8'))
    output.seek(0)

    return send_file(output, mimetype='text/csv', as_attachment=True, download_name='contacts.csv')

@app.route('/contacts/import_csv', methods=['GET', 'POST'])
def import_contacts_csv():
    if request.method == 'POST':
        file = request.files['csv_file']
        if not file or not file.filename.endswith('.csv'):
            return "Invalid file", 400

        stream = io.StringIO(file.stream.read().decode("utf-8"))
        reader = csv.DictReader(stream)

        imported_count = 0
        skipped_rows = []

        for idx, row in enumerate(reader, start=2):  # Start at 2 to match Excel (1 = header, 2 = first data row)
            missing_fields = []

            if not row.get('name'):
                missing_fields.append('name')
            if not row.get('role'):
                missing_fields.append('role')
            if not row.get('contact_type'):
                missing_fields.append('contact_type')

            if missing_fields:
                skipped_rows.append((idx, missing_fields))
                continue

            contact = Contact(
                name=row.get('name'),
                email=row.get('email') if row.get('email') and row['email'].lower() != 'none' else None,
                phone=row.get('phone'),
                role=row.get('role'),
                location=row.get('location'),
                technology=row.get('technology'),
                contact_type=row.get('contact_type'),
                notes=row.get('notes')
            )

            if row.get('reports_to'):
                manager = Contact.query.filter_by(name=row['reports_to']).first()
                if manager:
                    contact.reports_to = manager.id

            if row.get('customer_name'):
                customer = Customer.query.filter_by(name=row['customer_name']).first()
                if customer:
                    contact.customer_id = customer.id

            if row.get('partner_name'):
                partner = Partner.query.filter_by(name=row['partner_name']).first()
                if partner:
                    contact.partner_id = partner.id

            db.session.add(contact)
            db.session.flush()

            if row.get('division_name') and contact.customer_id:
                division = Division.query.filter_by(name=row['division_name'], customer_id=contact.customer_id).first()
                if division:
                    contact.divisions.append(division)

            imported_count += 1

        db.session.commit()

        # 💬 Print a report in terminal
        print(f"✅ Imported {imported_count} contacts successfully.")
        if skipped_rows:
            print("⚠️ Skipped rows:")
            for row_num, missing in skipped_rows:
                print(f"  - Row {row_num}: Missing fields {', '.join(missing)}")
        else:
            print("🎉 No skipped rows.")

        return redirect(url_for('contact_list'))

    return render_template('import_contacts.html')


@app.route('/partners')
def partner_list():
    return render_template('partners.html', partners=Partner.query.all())

@app.route('/partners/add', methods=['GET', 'POST'])
def add_partner():
    customers = Customer.query.order_by(Customer.name).all()

    if request.method == 'POST':
        partner = Partner(
            name=request.form['name'],
            notes=request.form.get('notes')
        )

        customer_ids = request.form.getlist('customer_ids')
        for cid in customer_ids:
            customer = Customer.query.get(int(cid))
            if customer:
                partner.customers.append(customer)

        db.session.add(partner)
        log_change("Added partner", partner.name)
        db.session.commit()

        if request.args.get('from') == 'settings':
            return redirect(url_for('settings', tab='partners'))
        return redirect(url_for('partner_list'))

    return render_template('add_partner.html', customers=customers)


@app.route('/partners/edit/<int:partner_id>', methods=['GET', 'POST'])
def edit_partner(partner_id):
    partner = Partner.query.get_or_404(partner_id)
    customers = Customer.query.order_by(Customer.name).all()

    if request.method == 'POST':
        partner.name = request.form['name']
        partner.notes = request.form.get('notes')

        # Update assigned customers
        customer_ids = request.form.getlist('customer_ids')
        partner.customers = Customer.query.filter(Customer.id.in_(customer_ids)).all()

        db.session.commit()
        log_change("Edited partner", partner.name)

        if request.args.get('from') == 'settings':
            return redirect(url_for('settings', tab='partners'))
        return redirect(url_for('partner_list'))

    return render_template('edit_partner.html', partner=partner, customers=customers)


@app.route('/partners/delete/<int:partner_id>', methods=['POST'])
def delete_partner(partner_id):
    partner = Partner.query.get_or_404(partner_id)
    confirm_name = request.form.get("confirm_name", "").strip()

    if confirm_name != partner.name:
        return redirect(url_for('settings', tab='partners', msg='confirm_failed'))

    # Disassociate the partner from linked customers
    for customer in partner.customers:
        customer.partners.remove(partner)

    # Disassociate the partner from contacts
    for contact in partner.contacts:
        contact.partner_id = None

    log_change("Deleted partner", partner.name)
    db.session.delete(partner)
    db.session.commit()

    if request.args.get('from') == 'settings':
        return redirect(url_for('settings', tab='partners', msg='deleted'))

    return redirect(url_for('partner_list'))

    if request.args.get('from') == 'settings':
        return redirect(url_for('settings', tab='partners'))
    return redirect(url_for('partner_list'))


@app.route('/partners/<int:partner_id>')
def partner_detail(partner_id):
    partner = Partner.query.get_or_404(partner_id)
    return render_template('partner_detail.html', partner=partner)



# --- CUSTOMER ROUTES ---
# --- CUSTOMER ROUTES ---
# --- CUSTOMER ROUTES ---



@app.route('/customers')
def customer_list():
    return render_template('customers.html', customers=Customer.query.all())

def build_contact_tree(contacts):
    id_map = {c.id: c for c in contacts}
    tree = []

    for contact in contacts:
        manager_id = contact.reports_to
        if manager_id and manager_id in id_map:
            manager = id_map[manager_id]
            if not hasattr(manager, 'subordinates'):
                manager.subordinates = []
            manager.subordinates.append(contact)
        else:
            tree.append(contact)
    return tree


@app.route('/customer/<int:id>')
def customer_detail(id):
    customer = Customer.query.options(joinedload(Customer.meetings)).get_or_404(id)
    contact_tree = build_contact_tree(customer.contacts)
    past_meetings = sorted(customer.meetings, key=lambda m: m.date, reverse=True)

    root_docs, division_docs = get_customer_attachments(customer.id)

    # 🧹 Exclude hidden files (e.g., .DS_Store)
    root_docs = [d for d in root_docs if not os.path.basename(d.filename).startswith('.')]
    division_docs = [d for d in division_docs if not os.path.basename(d.filename).startswith('.')]

    total_attachments = len(root_docs) + len(division_docs)

    return render_template(
        'customer_detail.html',
        customer=customer,
        contact_tree=contact_tree,
        past_meetings=past_meetings,
        total_attachments=total_attachments
    )
@app.route('/customers/add', methods=['GET', 'POST'])
def add_customer():
    if request.method == 'POST':
        customer_name = request.form['name']
        customer = Customer(
            name=customer_name,
            cx_services=request.form.get('cx_services'),
            notes=request.form.get('notes')
        )

        # Relationships
        partner_ids = request.form.getlist('partners')
        contact_ids = request.form.getlist('contacts')
        for pid in partner_ids:
            partner = Partner.query.get(int(pid))
            customer.partners.append(partner)
        for cid in contact_ids:
            contact = Contact.query.get(int(cid))
            customer.contacts.append(contact)

        db.session.add(customer)
        db.session.commit()

        # ✅ Save logo if uploaded
        logo_file = request.files.get('logo')
        if logo_file and logo_file.filename.lower().endswith('.png'):
            safe_name = customer.name.replace(" ", "_").lower()
            logo_path = os.path.join(app.config['LOGO_UPLOAD_FOLDER'], f"{safe_name}.png")
            logo_file.save(logo_path)
            print(f"✅ Saved logo to: {logo_path}")
        else:
            print("⚠️ No logo uploaded or wrong file type.")


        # ✅ Optional division file handling...
        division_name = request.form.get('division_name')
        division_file = request.files.get('division_file')
        if division_name:
            filename = None
            if division_file:
                filename = secure_filename(division_file.filename)
                division_file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            division = Division(name=division_name, customer_id=customer.id, document=filename)
            db.session.add(division)
            db.session.commit()

        if request.args.get('from') == 'settings':
            return redirect(url_for('settings', tab='customers'))
        return redirect(url_for('customer_list'))

    contacts = Contact.query.filter(Contact.customer_id == None, Contact.partner_id == None).all()
    partners = Partner.query.all()
    return render_template('add_customer.html', contacts=contacts, partners=partners)


@app.route('/customers/edit/<int:id>', methods=['GET', 'POST'])
def edit_customer(id):
    customer = Customer.query.get_or_404(id)

    if request.method == 'POST':
        customer.name = request.form['name']
        customer.cx_services = request.form.get('cx_services')
        customer.notes = request.form.get('notes')

        # ✅ Handle logo upload
        logo = request.files.get('logo')
        if logo and logo.filename.endswith('.png'):
            safe_name = customer.name.replace(" ", "_").lower() + ".png"
            logo_path = os.path.join('static', 'logos', safe_name)
            os.makedirs(os.path.dirname(logo_path), exist_ok=True)
            logo.save(logo_path)

        log_change("Edited customer", customer.name)
        db.session.commit()

        return redirect(url_for('customer_detail', id=customer.id))

    return render_template('edit_customer.html', customer=customer, available_contacts=Contact.query.all())

@app.route('/customers/delete/<int:id>', methods=['POST'])
def delete_customer(id):
    customer = Customer.query.get_or_404(id)

    # 🔒 Confirm typed name matches customer name
    confirm_name = request.form.get("confirm_name", "").strip()
    if confirm_name != customer.name:
        return redirect(url_for("settings", tab="customers", msg="confirm_failed"))

    # 🔄 Disassociate relationships
    for item in customer.action_items:
        item.customer_id = None
    for meeting in customer.meetings:
        meeting.customer_id = None
    for recurring in customer.recurring_meetings:
        recurring.customer_id = None
    for contact in customer.contacts:
        contact.customer_id = None
        contact.contact_type = "Unassigned"
    for division in customer.divisions:
        division.customer_id = None

    log_change("Deleted customer", customer.name)
    db.session.commit()  # commit disassociations

    db.session.delete(customer)
    db.session.commit()

    if request.args.get("from") == "settings":
        return redirect(url_for("settings", tab="customers", msg="deleted"))
    return redirect(url_for('customer_list'))


@app.route('/customers/<int:id>/upload', methods=['POST'])
def upload_customer_file(id):
    customer = Customer.query.get_or_404(id)
    files = request.files.getlist('files')
    if not files:
        return redirect(url_for('customer_attachments', id=customer.id))

    # Create or find root division
    root_division = Division.query.filter_by(customer_id=customer.id, parent_id=None).first()
    if not root_division:
        root_division = Division(name=customer.name, customer_id=customer.id)
        db.session.add(root_division)
        db.session.commit()

    # ✅ Clean customer name for folder (removes special characters)
    safe_name = secure_folder_name(customer.name)
    customer_folder = os.path.join(app.config['UPLOAD_FOLDER'], safe_name)
    os.makedirs(customer_folder, exist_ok=True)

    for file in files:
        if file and file.filename:
            filename = file.filename.replace(' ', '_')  # optionally sanitize further
            file_path = os.path.join(customer_folder, filename)
            file.save(file_path)
            rel_path = os.path.join(safe_name, filename)  # this ensures: "Riot_Games/file.pdf"
            doc = DivisionDocument(division_id=root_division.id, filename=rel_path)

            db.session.add(doc)  # ✅ THIS LINE IS MANDATORY

    db.session.commit()
    return redirect(url_for('customer_attachments', id=customer.id))

@app.route('/customers/<int:id>/attachments')
def customer_attachments(id):
    sync_customer_files_logic(id)  # auto-sync before rendering
    customer = Customer.query.get_or_404(id)
    root_docs, division_docs = get_customer_attachments(customer.id)

    # 🧹 Exclude hidden files
    root_docs = [d for d in root_docs if not os.path.basename(d.filename).startswith('.')]
    division_docs = [d for d in division_docs if not os.path.basename(d.filename).startswith('.')]

    total_attachments = len(root_docs) + len(division_docs)

    return render_template(
        'customer_attachments.html',
        customer=customer,
        root_docs=root_docs,
        division_docs=division_docs,
        safe_customer_name=secure_folder_name(customer.name)
    )

# --- Customer Opportunities ---
@app.route('/customers/<int:customer_id>/add_opportunity', methods=['POST'])
def add_customer_opportunity(customer_id):
    customer = Customer.query.get_or_404(customer_id)
    title = request.form['title']
    value = request.form.get('value')
    stage = request.form.get('stage')
    notes = request.form.get('notes')

    new_opp = CustomerOpportunity(customer_id=customer.id, title=title, value=value, stage=stage, notes=notes)
    db.session.add(new_opp)
    log_change("Added customer opportunity", title)
    db.session.commit()
    return redirect(url_for('customer_detail', id=customer.id))


# --- Customer Technologies ---
@app.route('/customers/<int:customer_id>/add_technology', methods=['POST'])
def add_customer_technology(customer_id):
    customer = Customer.query.get_or_404(customer_id)
    name = request.form['name']
    discount_level = request.form.get('discount_level', type=int)
    notes = request.form.get('notes')

    new_tech = CustomerTechnology(customer_id=customer.id, name=name, discount_level=discount_level, notes=notes)
    db.session.add(new_tech)
    log_change("Added customer technology", name)
    db.session.commit()
    return redirect(url_for('customer_detail', id=customer.id))


# --- Customer Projects ---
@app.route('/customers/<int:customer_id>/add_project', methods=['POST'])
def add_customer_project(customer_id):
    customer = Customer.query.get_or_404(customer_id)
    name = request.form['name']
    status = request.form.get('status')
    owner = request.form.get('owner')
    notes = request.form.get('notes')

    new_proj = CustomerProject(customer_id=customer.id, name=name, status=status, owner=owner, notes=notes)
    db.session.add(new_proj)
    log_change("Added customer project", name)
    db.session.commit()
    return redirect(url_for('customer_detail', id=customer.id))

@app.route('/customers/delete_file/<int:file_id>', methods=['POST'])
def delete_customer_file(file_id):
    doc = DivisionDocument.query.get_or_404(file_id)
    full_path = os.path.abspath(os.path.join(app.config['UPLOAD_FOLDER'], doc.filename))

    if not full_path.startswith(os.path.abspath(app.config['UPLOAD_FOLDER'])):
        abort(403)

    try:
        if os.path.exists(full_path):
            os.remove(full_path)
            print(f"🗑️ Deleted file: {full_path}")
    except Exception as e:
        print(f"⚠️ Error deleting file: {e}")

    db.session.delete(doc)
    db.session.commit()

    open_folder = request.args.get('open')
    ref = request.form.get('referer') or request.referrer or url_for('customer_list')
    if open_folder and ref:
        # Remove existing ? or &open=... from the ref
        ref = ref.split('?')[0]
        return redirect(f"{ref}?open={open_folder}")
    return redirect(ref or url_for('customer_list'))



# --- DIVISION ROUTES ---
# --- DIVISION ROUTES ---
# --- DIVISION ROUTES ---



@app.route('/divisions/add/<int:customer_id>', methods=['GET', 'POST'])
def add_division(customer_id):
    customer = Customer.query.get_or_404(customer_id)

    # Ensure root division exists
    root = Division.query.filter_by(customer_id=customer.id, parent_id=None).first()
    if not root:
        root = Division(name=customer.name, customer_id=customer.id)
        db.session.add(root)
        db.session.commit()

    if request.method == 'POST':
        name = request.form['name']
        document = None

        # Handle optional document upload
        file = request.files.get('document')
        if file and file.filename:
            filename = secure_filename(file.filename)
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            document = filename

        # Always assign to root
        division = Division(
            name=name,
            customer_id=customer.id,
            parent_id=root.id,
            document=document
        )
        db.session.add(division)
        db.session.commit()
        return redirect(url_for('customer_detail', id=customer.id))

    return render_template('add_division.html', customer=customer)

@app.route('/divisions/<int:division_id>/assign_contacts', methods=['GET', 'POST'])
def assign_contacts_to_division(division_id):
    division = Division.query.get_or_404(division_id)
    customer = division.customer
    available_contacts = Contact.query.filter_by(customer_id=customer.id).all()

    if request.method == 'POST':
        selected_ids = request.form.getlist('contact_ids')
        selected_contacts = Contact.query.filter(Contact.id.in_(selected_ids)).all()

        # Reset and reassign contacts
        division.contacts = selected_contacts

        db.session.commit()
        return redirect(url_for('division_detail', division_id=division.id))

    return render_template(
        'assign_contacts_to_division.html',
        division=division,
        customer=customer,
        contacts=available_contacts
    )

@app.route('/division/<int:division_id>')
def division_detail(division_id):
    division = Division.query.get_or_404(division_id)
    return render_template(
        'division_detail.html',
        division=division,
        customer=division.customer  # 🔥 this line fixes the error
    )
@app.route('/division/<int:division_id>/delete', endpoint='delete_division')
def delete_division_route(division_id):

    division = Division.query.get_or_404(division_id)
    customer_id = division.customer_id
    from_tab = request.args.get('from')

    db.session.delete(division)
    db.session.commit()

    if from_tab == "setup":
        return redirect(url_for('customer_detail', id=customer_id) + '#setup')
    return redirect(url_for('customer_detail', id=customer_id))


@app.route('/divisions/<int:division_id>/opportunities/add', methods=['GET', 'POST'])
def add_division_opportunity(division_id):
    division = Division.query.get_or_404(division_id)

    if request.method == 'POST':
        opp = DivisionOpportunity(
            division_id=division_id,
            title=request.form['title'],
            value=request.form.get('value'),
            stage=request.form.get('stage'),
            notes=request.form.get('notes')
        )
        db.session.add(opp)
        db.session.commit()

        if request.args.get('from') == 'setup':
            return redirect(url_for('customer_detail', id=division.customer_id) + '#setup')
        return redirect(url_for('division_detail', division_id=division_id))

    return render_template('division_opportunity_form.html', division_id=division_id)

@app.route('/divisions/opportunities/<int:id>/edit', methods=['GET', 'POST'])
def edit_division_opportunity(id):
    opp = DivisionOpportunity.query.get_or_404(id)
    if request.method == 'POST':
        opp.title = request.form['title']
        opp.value = request.form.get('value')
        opp.stage = request.form.get('stage')
        opp.notes = request.form.get('notes')
        db.session.commit()

        redirect_target = request.args.get('from')
        if redirect_target == 'setup':
            return redirect(url_for('customer_detail', id=opp.division.customer_id) + '#setup')
        return redirect(url_for('division_detail', division_id=opp.division_id))

    return render_template('division_opportunity_form.html', opportunity=opp)

@app.route('/divisions/opportunities/<int:id>/delete', methods=['GET'])
def delete_division_opportunity(id):
    opp = DivisionOpportunity.query.get_or_404(id)
    customer_id = opp.division.customer_id
    db.session.delete(opp)
    db.session.commit()

    if request.args.get('from') == 'setup':
        return redirect(url_for('customer_detail', id=customer_id) + '#setup')
    return redirect(url_for('division_detail', division_id=opp.division_id))


# --- Division Technologies ---
@app.route('/divisions/<int:division_id>/technologies/add', methods=['GET', 'POST'])
def add_division_technology(division_id):
    division = Division.query.get_or_404(division_id)

    if request.method == 'POST':
        tech = DivisionTechnology(
            division_id=division_id,
            name=request.form['name'],
            discount_level=request.form.get('discount_level', type=int),
            notes=request.form.get('notes')
        )
        db.session.add(tech)
        db.session.commit()

        if request.args.get('from') == 'setup':
            return redirect(url_for('customer_detail', id=division.customer_id) + '#setup')
        return redirect(url_for('division_detail', division_id=division_id))

    return render_template('division_technology_form.html', division_id=division_id)
@app.route('/divisions/technologies/<int:id>/edit', methods=['GET', 'POST'])
def edit_division_technology(id):
    tech = DivisionTechnology.query.get_or_404(id)
    if request.method == 'POST':
        tech.name = request.form['name']
        tech.discount_level = request.form.get('discount_level', type=int)
        tech.notes = request.form.get('notes')
        db.session.commit()

        redirect_target = request.args.get('from')
        if redirect_target == 'setup':
            return redirect(url_for('customer_detail', id=tech.division.customer_id) + '#setup')
        return redirect(url_for('division_detail', division_id=tech.division_id))

    return render_template('division_technology_form.html', technology=tech)


@app.route('/divisions/technologies/<int:id>/delete')
def delete_division_technology(id):
    tech = DivisionTechnology.query.get_or_404(id)
    customer_id = tech.division.customer_id
    db.session.delete(tech)
    db.session.commit()

    redirect_target = request.args.get('from')
    if redirect_target == 'setup':
        return redirect(url_for('customer_detail', id=customer_id) + '#setup')
    return redirect(url_for('division_detail', division_id=tech.division_id))


# --- Division Projects ---
@app.route('/divisions/<int:division_id>/projects/add', methods=['GET', 'POST'])
def add_division_project(division_id):
    division = Division.query.get_or_404(division_id)

    if request.method == 'POST':
        proj = DivisionProject(
            division_id=division_id,
            name=request.form['name'],
            status=request.form.get('status'),
            owner=request.form.get('owner'),
            notes=request.form.get('notes')
        )
        db.session.add(proj)
        db.session.commit()

        if request.args.get('from') == 'setup':
            return redirect(url_for('customer_detail', id=division.customer_id) + '#setup')
        return redirect(url_for('division_detail', division_id=division_id))

    return render_template('division_project_form.html', division_id=division_id)

@app.route('/divisions/projects/<int:id>/edit', methods=['GET', 'POST'])
def edit_division_project(id):
    proj = DivisionProject.query.get_or_404(id)
    if request.method == 'POST':
        proj.name = request.form['name']
        proj.status = request.form.get('status')
        proj.owner = request.form.get('owner')
        proj.notes = request.form.get('notes')
        db.session.commit()

        redirect_target = request.args.get('from')
        if redirect_target == 'setup':
            return redirect(url_for('customer_detail', id=proj.division.customer_id) + '#setup')
        return redirect(url_for('division_detail', division_id=proj.division_id))

    return render_template('division_project_form.html', project=proj)


@app.route('/divisions/projects/<int:id>/delete', endpoint='delete_division_project')
def delete_division_project(id):

    proj = DivisionProject.query.get_or_404(id)
    customer_id = proj.division.customer_id
    db.session.delete(proj)
    db.session.commit()

    redirect_target = request.args.get('from')
    if redirect_target == 'setup':
        return redirect(url_for('customer_detail', id=customer_id) + '#setup')
    return redirect(url_for('division_detail', division_id=proj.division_id))

# Modified upload route for division

@app.route('/division/<int:division_id>/upload', methods=['POST'])
def upload_division_document(division_id):
    division = Division.query.get_or_404(division_id)
    files = request.files.getlist('files')

    for file in files:
        if file and file.filename:
            filename = secure_filename(file.filename)
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            doc = DivisionDocument(division_id=division.id, filename=filename)
            db.session.add(doc)

    db.session.commit()
    return redirect(url_for('division_detail', division_id=division_id))

#--- UPLOAD ROUTES---

@app.route('/uploads/<path:filename>')
def uploaded_file(filename):
    safe_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    if not os.path.isfile(safe_path):
        abort(404)
    return send_file(safe_path)

from datetime import datetime


# --- ACTION ITEM ROUTES ---
# --- ACTION ITEM ROUTES ---
# --- ACTION ITEM ROUTES ---

@app.route('/action_items')
def action_item_list():
    customer_id = request.args.get('customer_id')
    tab = request.args.get('tab', 'daily')
    all_customers = Customer.query.order_by(Customer.name).all()

    query = ActionItem.query
    if customer_id:
        query = query.filter_by(customer_id=customer_id)

    all_items = query.all()

    # ✅ Updated logic: latest update OR creation date
    def latest_or_created(item):
        try:
            created = datetime.strptime(item.date, '%Y-%m-%d')
        except Exception:
            created = datetime.min

        if item.updates:
            latest_update_time = max(update.timestamp for update in item.updates)
            return max(created, latest_update_time)
        return created

    sorted_items = sorted(all_items, key=latest_or_created, reverse=True)

    daily_items = [item for item in sorted_items if item.category == 'daily']
    strategic_items = [item for item in sorted_items if item.category == 'strategic']

    return render_template(
        'action_items.html',
        daily_items=daily_items,
        strategic_items=strategic_items,
        all_customers=all_customers,
        selected_customer_id=customer_id,
        active_tab=tab
    )

@app.route('/action_items/add', methods=['GET', 'POST'])
def add_action_item():
    if request.method == 'POST':
        item = ActionItem(
            date=request.form['date'],
            detail=request.form['detail'],
            customer_id=request.form['customer_id'],
            customer_contact=request.form['customer_contact'],
            cisco_contact=request.form['cisco_contact'],
            completed='completed' in request.form,
            category=request.form.get('category', 'daily')
        )
        db.session.add(item)
        db.session.commit()
        log_change("Added action item", f"{item.detail} (Customer ID: {item.customer_id})")
        return redirect(url_for('action_item_list', tab=item.category))
    
    customers = Customer.query.all()
    return render_template('add_action_item.html', customers=customers, current_date=date.today().isoformat())

@app.route('/action_items/delete/<int:item_id>')
def delete_action_item(item_id):
    item = ActionItem.query.get_or_404(item_id)
    category = item.category  # ✅ Capture the current category before deletion
    log_change("Deleted action item", f"{item.detail} (Customer ID: {item.customer_id})")
    db.session.delete(item)
    db.session.commit()
    return redirect(url_for('action_item_list', tab=category))

@app.route('/action_items/edit/<int:item_id>', methods=['GET', 'POST'])
def edit_action_item(item_id):
    item = ActionItem.query.get_or_404(item_id)
    tab = request.args.get('tab', 'daily')  # ← Capture tab from query string

    if request.method == 'POST':
        item.date = request.form['date']
        item.detail = request.form['detail']
        item.customer_id = request.form['customer_id']
        item.customer_contact = request.form['customer_contact']
        item.cisco_contact = request.form['cisco_contact']
        item.completed = 'completed' in request.form
        item.category = request.form.get('category', item.category)  # ← Allow changing category
        db.session.commit()
        log_change("Edited action item", f"{item.detail} (Customer ID: {item.customer_id})")


        # Redirect to correct tab based on (possibly updated) category
        return redirect(url_for('action_item_list', tab=item.category))

    customers = Customer.query.all()
    return render_template(
        'edit_action_item.html',
        item=item,
        customers=customers,
        active_tab=tab
    )


@app.route('/action_items/<int:item_id>/add_update', methods=['POST'])
def add_action_item_update(item_id):
    from datetime import datetime
    text = request.form.get('update_text')
    if text:
        update = ActionItemUpdate(
            action_item_id=item_id,
            update_text=text,
            timestamp=datetime.now()  # or datetime.utcnow() if you prefer UTC
        )
        db.session.add(update)
        db.session.commit()
        log_change("Added action item update", f"Item ID: {item_id} – {text[:50]}")

    return redirect(url_for('edit_action_item', item_id=item_id))

@app.route('/action_items/update/<int:update_id>/edit', methods=['POST'])
def edit_action_item_update(update_id):
    update = ActionItemUpdate.query.get_or_404(update_id)
    update_text = request.form.get('update_text')
    item_id = request.form.get('item_id')

    if not item_id:
        return "Missing item_id in form submission", 400

    if update_text:
        update.update_text = update_text
        update.timestamp = datetime.now()
        db.session.commit()
        log_change("Edited action item update", f"Update ID: {update_id} – {update_text[:50]}")

    return redirect(url_for('edit_action_item', item_id=item_id))

@app.route('/action_items/update/<int:update_id>/delete', methods=['POST'])
def delete_action_item_update(update_id):
    update = ActionItemUpdate.query.get_or_404(update_id)
    item = update.parent  # or ActionItem.query.get(update.action_item_id)

    tab = request.args.get('tab', item.category)  # ← Get tab from request, fallback to current category
    log_change("Deleted action item update", f"Update ID: {update_id} (Item ID: {item.id})")
    db.session.delete(update)
    db.session.commit()

    return redirect(url_for('edit_action_item', item_id=item.id, tab=tab))


@app.route('/action_items/export_csv')
def export_action_items_csv():
    from io import StringIO
    import csv
    from datetime import date

    si = StringIO()
    writer = csv.writer(si)

    # Headers
    writer.writerow(['Category', 'Date', 'Detail + Updates', 'Customer', 'Customer Contact', 'Cisco Contact', 'Status'])

    # Fetch items
    strategic_items = ActionItem.query.filter_by(category='strategic').order_by(ActionItem.date.desc()).all()
    daily_items = ActionItem.query.filter_by(category='daily').order_by(ActionItem.date.desc()).all()

    # Helper to write rows
    def write_items(items, category_label):
        for item in items:
            # Combine detail + update into single text block
            detail_text = item.detail or ''
            if item.updates:
                updates_combined = '\n\n'.join(f"- {u.timestamp.strftime('%Y-%m-%d %H:%M')} – {u.update_text}" for u in item.updates)
                detail_text = f"{detail_text}\n\n--- Updates ---\n{updates_combined}"

            writer.writerow([
                category_label,
                item.date or '',
                detail_text.strip(),
                item.customer.name if item.customer else '',
                item.customer_contact or '',
                item.cisco_contact or '',
                'Completed' if item.completed else 'Open'
            ])

    # First Strategic
    write_items(strategic_items, 'Strategic')

    # Then Daily
    write_items(daily_items, 'Day-to-Day')

    # Prepare for download
    output = si.getvalue().encode('utf-8')
    buffer = io.BytesIO(output)
    buffer.seek(0)

    today_str = date.today().isoformat()
    filename = f"action_items_export_{today_str}.csv"

    return send_file(
        buffer,
        mimetype='text/csv',
        as_attachment=True,
        download_name=filename
    )

# --- MEETINGS ROUTES ---
# --- MEETINGS ROUTES ---
# --- MEETINGS ROUTES ---


@app.route('/meetings')
def meeting_list():
    customer_id = request.args.get('customer_id', type=int)
    search_query = request.args.get('q', '').strip()
    customers = Customer.query.order_by(Customer.name).all()

    meetings = Meeting.query

    if customer_id:
        meetings = meetings.filter(Meeting.customer_id == customer_id)

    if search_query:
        meetings = meetings.filter(
            (Meeting.title.ilike(f"%{search_query}%")) |
            (Meeting.notes.ilike(f"%{search_query}%")) |
            (Meeting.host.ilike(f"%{search_query}%"))
        )

    meetings = meetings.order_by(Meeting.date.desc()).all()

    return render_template(
        'meetings.html',
        meetings=meetings,
        customers=customers,
        selected_customer_id=customer_id,
        search_query=search_query
    )

# Redirect fix for meeting add route
def redirect_back(fallback_endpoint=None, fallback_kwargs=None):
    next_url = request.args.get('next')
    if next_url:
        return redirect(next_url)
    elif fallback_endpoint:
        return redirect(url_for(fallback_endpoint, **(fallback_kwargs or {})))
    return redirect('/')

@app.route('/meetings/add', methods=['GET', 'POST'])
def add_meeting():
    if request.method == 'POST':
        meeting = Meeting(
            customer_id=request.form['customer_id'],
            date=request.form['date'],
            title=request.form['title'],
            host=request.form['host'],
            notes=request.form.get('notes')
        )
        participant_ids = request.form.getlist('participants')
        for cid in participant_ids:
            contact = Contact.query.get(int(cid))
            meeting.participants.append(contact)
        db.session.add(meeting)
        db.session.commit()
        log_change("Added meeting", f"{meeting.title} for {meeting.customer.name} on {meeting.date}")
        return redirect_back(fallback_endpoint='meeting_list')  # 👈 updated
        
    customers = Customer.query.all()
    contacts = Contact.query.all()
    selected_customer_id = request.args.get('customer_id', type=int)  # 👈 get it from URL
    current_date = date.today().strftime('%Y-%m-%d')  # ✅ Provide today's date

    return render_template('add_meeting.html', customers=customers, contacts=contacts, current_date=datetime.today().date(), selected_customer_id=selected_customer_id)


@app.route('/meetings/edit/<int:meeting_id>', methods=['GET', 'POST'])
def edit_meeting(meeting_id):
    meeting = Meeting.query.get_or_404(meeting_id)
    if request.method == 'POST':
        meeting.date = request.form['date']
        meeting.title = request.form['title']
        meeting.host = request.form['host']
        meeting.notes = request.form.get('notes')
        db.session.commit()
        log_change("Edited meeting", f"{meeting.title} (ID: {meeting.id}) for {meeting.customer.name}")
        return redirect(url_for('meeting_list'))
    return render_template('edit_meeting.html', meeting=meeting)

@app.route('/meetings/delete/<int:meeting_id>')
def delete_meeting(meeting_id):
    meeting = Meeting.query.get_or_404(meeting_id)
    log_change("Deleted meeting", f"{meeting.title} (ID: {meeting.id}) for {meeting.customer.name}")
    db.session.delete(meeting)
    db.session.commit()
    return redirect(url_for('meeting_list'))


# --- RECURRING MEETINGS ROUTES ---
# --- RECURRING MEETINGS ROUTES ---
# --- RECURRING MEETINGS ROUTES ---


@app.route('/recurring_meetings')
def recurring_meeting_list():
    customer_id = request.args.get('customer_id', type=int)
    customers = Customer.query.order_by(Customer.name).all()

    if customer_id:
        meetings = RecurringMeeting.query.filter_by(customer_id=customer_id).order_by(RecurringMeeting.start_datetime.desc()).all()
    else:
        meetings = RecurringMeeting.query.order_by(RecurringMeeting.start_datetime.desc()).all()

    # --- Find meetings happening today ---
    today = datetime.today().date()
    meetings_today = []
    for meeting in meetings:
        next_occurrence = meeting.get_next_occurrence(today=datetime.combine(today, datetime.min.time()))
        if next_occurrence and next_occurrence.date() == today:
            meetings_today.append(meeting)

    return render_template('recurring_meetings.html', 
                           meetings=meetings, 
                           customers=customers, 
                           selected_customer_id=customer_id,
                           meetings_today=meetings_today)

@app.template_filter('recurrence_display')
def recurrence_display(meeting):
    if not meeting or not meeting.recurrence_pattern or not meeting.start_datetime:
        return "—"

    dt = meeting.start_datetime
    weekday = dt.strftime('%A')
    time_str = dt.strftime('%I:%M %p').lstrip('0')

    if meeting.recurrence_pattern == 'daily':
        return f"Repeats daily at {time_str}"
    elif meeting.recurrence_pattern == 'weekly':
        return f"Repeats every {weekday} at {time_str}"
    elif meeting.recurrence_pattern == 'biweekly':
        return f"Repeats every other {weekday} at {time_str}"
    elif meeting.recurrence_pattern == 'monthly':
        day = dt.day
        return f"Repeats monthly on the {day}{ordinal(day)} at {time_str}"
    else:
        return f"Repeats: {meeting.recurrence_pattern} at {time_str}"

def ordinal(n):
    return "th" if 11 <= n % 100 <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")


@app.route('/recurring_meetings/add', methods=['GET', 'POST'])
def add_recurring_meeting():
    if request.method == 'POST':
        title = request.form['title']
        start_datetime = datetime.strptime(request.form['start_datetime'], '%Y-%m-%dT%H:%M')
        customer_id = request.form['customer_id']
        host = request.form['host']
        recurrence_pattern = request.form['recurrence_pattern']
        repeat_until = datetime.strptime(request.form['repeat_until'], '%Y-%m-%d').date()
        description = request.form.get('description')
        generate_ics = 'generate_ics' in request.form
        duration = request.form.get('duration_minutes', type=int) or 60

        meeting = RecurringMeeting(
            title=title,
            start_datetime=start_datetime,
            customer_id=customer_id,
            host=host,
            recurrence_pattern=recurrence_pattern,
            repeat_until=repeat_until,
            description=description,
            duration_minutes=duration,
            generate_ics=generate_ics
        )

        db.session.add(meeting)
        db.session.commit()
        log_change("Added recurring meeting", f"{meeting.title} every {meeting.recurrence_pattern} for {meeting.customer.name}")

        if generate_ics:
            cal = Calendar()
            event = Event()

            event.add('summary', title)
            event.add('dtstart', start_datetime)
            event.add('dtend', start_datetime + timedelta(minutes=duration))
            event.add('description', description or '')
            event.add('location', f"Customer ID: {customer_id}")

            freq_map = {
                'daily': 'DAILY',
                'weekly': 'WEEKLY',
                'biweekly': 'WEEKLY',
                'monthly': 'MONTHLY'
            }
            rrule = {
                'FREQ': freq_map.get(recurrence_pattern, 'WEEKLY'),
                'INTERVAL': 2 if recurrence_pattern == 'biweekly' else 1,
                'UNTIL': repeat_until
            }
            event.add('rrule', rrule)

            cal.add_component(event)

            ics_bytes = io.BytesIO(cal.to_ical())
            ics_bytes.seek(0)

            return send_file(
                ics_bytes,
                mimetype='text/calendar',
                as_attachment=True,
                download_name=f"{title.replace(' ', '_')}.ics"
            )

        return redirect(url_for('recurring_meeting_list'))

    customers = Customer.query.all()
    return render_template('add_recurring_meeting.html', customers=customers)

@app.route('/recurring_meetings/edit/<int:meeting_id>', methods=['GET', 'POST'])
def edit_recurring_meeting(meeting_id):
    meeting = RecurringMeeting.query.get_or_404(meeting_id)
    
    if request.method == 'POST':
        meeting.start_datetime = datetime.strptime(request.form['start_datetime'], '%Y-%m-%dT%H:%M')
        meeting.title = request.form['title']
        meeting.customer_id = int(request.form['customer_id'])
        meeting.host = request.form['host']
        meeting.recurrence_pattern = request.form['recurrence_pattern']
        meeting.repeat_until = datetime.strptime(request.form['repeat_until'], '%Y-%m-%d').date() if request.form['repeat_until'] else None
        meeting.description = request.form.get('description')
        meeting.duration_minutes = request.form.get('duration_minutes', type=int) or 60

        db.session.commit()
        log_change("Edited recurring meeting", f"{meeting.title} (ID: {meeting.id}) for {meeting.customer.name}")
        return redirect(url_for('recurring_meeting_list'))

    customers = Customer.query.all()
    return render_template('edit_recurring_meeting.html', meeting=meeting, customers=customers)

@app.route('/recurring_meetings/delete/<int:meeting_id>')
def delete_recurring_meeting(meeting_id):
    meeting = RecurringMeeting.query.get_or_404(meeting_id)
    log_change("Deleted recurring meeting", f"{meeting.title} (ID: {meeting.id}) for {meeting.customer.name}")
    db.session.delete(meeting)
    db.session.commit()
    return redirect(url_for('recurring_meeting_list'))

@app.route('/recurring_meetings/<int:meeting_id>/download_ics')
def download_recurring_ics(meeting_id):
    meeting = RecurringMeeting.query.get_or_404(meeting_id)

    cal = Calendar()
    event = Event()

    event.add('summary', meeting.title)
    event.add('dtstart', meeting.start_datetime)
    event.add('dtend', meeting.start_datetime + timedelta(minutes=meeting.duration_minutes or 60))
    event.add('description', meeting.description or '')
    event.add('location', meeting.customer.name)

    # ✅ Add RRULE
    freq_map = {
        'daily': 'DAILY',
        'weekly': 'WEEKLY',
        'biweekly': 'WEEKLY',
        'monthly': 'MONTHLY'
    }
    rrule = {
        'FREQ': freq_map.get(meeting.recurrence_pattern, 'WEEKLY'),
        'INTERVAL': 2 if meeting.recurrence_pattern == 'biweekly' else 1,
        'UNTIL': meeting.repeat_until  # should be datetime.date or datetime
    }
    event.add('rrule', rrule)

    cal.add_component(event)

    # Write .ics to memory
    ics_bytes = io.BytesIO(cal.to_ical())
    ics_bytes.seek(0)

    return send_file(
        ics_bytes,
        mimetype='text/calendar',
        as_attachment=True,
        download_name=f"{meeting.title.replace(' ', '_')}.ics"
    )

# --- BACKUP ROUTES ---
# --- BACKUP ROUTES ---
# --- BACKUP ROUTES ---


@app.route('/backup_db')
def backup_db():
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

        log_change(f"[{DEVICE_NAME}] Manual backup", f"{filename}")
        return redirect(url_for('dashboard', msg='✅ Backup saved to OneDrive + Mac!'))

    except Exception as e:
        print(f"❌ Manual backup failed: {e}")
        return redirect(url_for('dashboard', msg='❌ Backup failed. Check server logs.'))
    
# --- Setup Tab Rendering ---
@app.context_processor
def inject_division_setup_links():
    def get_setup_links(customer):
        return [
            {
                'division': d,
                'links': {
                    'contacts': url_for('assign_contacts_to_division', division_id=d.id),
                    'opportunity': url_for('add_division_opportunity', division_id=d.id),
                    'technology': url_for('add_division_technology', division_id=d.id),
                    'project': url_for('add_division_project', division_id=d.id)
                }
            } for d in customer.divisions if d.parent_id
        ]
    return dict(get_setup_links=get_setup_links)

@app.context_processor
def inject_counts():
    return {
        'customer_count': Customer.query.count(),
        'contact_count': Contact.query.count(),
        'partner_count': Partner.query.count(),
        'action_item_open_count': ActionItem.query.filter_by(completed=False).count(),
        'meeting_count': Meeting.query.count(),
        'recurring_meeting_count': RecurringMeeting.query.count()
    }


@app.context_processor
def inject_attachment_logic():
    def customer_attachments(customer):
        root_divisions = [d for d in customer.divisions if d.parent_id is None and d.document]
        sub_divisions = [d for d in customer.divisions if d.parent_id is not None and d.document]
        return root_divisions, sub_divisions
    return dict(customer_attachments=customer_attachments)


@app.context_processor
def inject_meetings_today():
    from datetime import datetime

    today = datetime.today().date()
    meetings = RecurringMeeting.query.all()

    meetings_today = []
    for meeting in meetings:
        next_occurrence = meeting.get_next_occurrence(today=datetime.combine(today, datetime.min.time()))
        if next_occurrence and next_occurrence.date() == today:
            meetings_today.append(meeting)

    return dict(meetings_today=meetings_today)


#------------------ DASHBOARD ROUTES ---------------------

@app.route('/dashboard')
def dashboard():
    customers = Customer.query.order_by(Customer.name).all()

    customer_cards = []
    open_action_customers = []  # 🔥 list instead of just True/False

    for customer in customers:
        open_ais_count = ActionItem.query.filter_by(customer_id=customer.id, completed=False).count()

        if open_ais_count >= 5:  # 👈 Customize threshold (e.g., 5 or more)
            open_action_customers.append({
                'name': customer.name,
                'count': open_ais_count
            })

        customer_cards.append({
            'id': customer.id,
            'name': customer.name,
            'open_ais': open_ais_count,
            'past_meetings': Meeting.query.filter_by(customer_id=customer.id).count(),
            'recurring_meetings': RecurringMeeting.query.filter_by(customer_id=customer.id).count(),
        })

    # Existing recurring meetings check
    meetings = RecurringMeeting.query.all()
    today = datetime.today().date()
    meetings_today = []
    for meeting in meetings:
        next_occurrence = meeting.get_next_occurrence(today=datetime.combine(today, datetime.min.time()))
        if next_occurrence and next_occurrence.date() == today:
            meetings_today.append(meeting)

    return render_template(
        'dashboard.html',
        customer_cards=customer_cards,
        total_customers=len(customers),
        total_contacts=Contact.query.count(),
        total_partners=Partner.query.count(),
        total_meetings=Meeting.query.count(),
        total_recurring=RecurringMeeting.query.count(),
        open_actions=ActionItem.query.filter_by(completed=False).count(),
        meetings_today=meetings_today,
        open_action_customers=open_action_customers  # ✅ pass list instead of bool
    )

#------------------ HEATMAP ROUTES ---------------------
@app.route('/heatmap')
def heatmap():
    customers = Customer.query.order_by(Customer.name).all()
    heatmap_data = []

    for customer in customers:
        row = {"name": customer.name, "data": []}
        for column in COLUMNS:
            cell = HeatmapCell.query.filter_by(customer_id=customer.id, column_name=column).first()
            if cell and (cell.color or cell.text):
                row["data"].append({"color": cell.color, "text": cell.text})
            else:
                row["data"].append(None)
        heatmap_data.append(row)

    return render_template("heatmap.html", customers=heatmap_data, columns=COLUMNS)


@app.route('/save_heatmap', methods=['POST'])
def save_heatmap():
    raw_data = request.form.get('heatmap_data', '')

    for line in raw_data.strip().split('\n'):
        if not line.strip():
            continue

        try:
            customer_name, cells_raw = line.split('||')
            customer = Customer.query.filter_by(name=customer_name.strip()).first()
            if not customer:
                continue

            cell_values = cells_raw.split('|')
            if len(cell_values) != len(COLUMNS):
                continue

            for i, value in enumerate(cell_values):
                if '::' not in value:
                    color, text = '', ''
                else:
                    color, text = value.split('::', 1)

                column = COLUMNS[i]
                color = color.strip()
                text = text.strip()

                existing_cell = HeatmapCell.query.filter_by(customer_id=customer.id, column_name=column).first()

                if color or text:
                    if existing_cell:
                        existing_cell.color = color
                        existing_cell.text = text
                        db.session.add(existing_cell)
                    else:
                        new_cell = HeatmapCell(customer_id=customer.id, column_name=column, color=color, text=text)
                        db.session.add(new_cell)
                else:
                    if existing_cell:
                        db.session.delete(existing_cell)

        except Exception:
            continue

    db.session.commit()
    return redirect(url_for('heatmap', msg='✅ Heatmap saved!'))


@app.route('/reset_heatmap')
def reset_heatmap():
    HeatmapCell.query.delete()
    db.session.commit()
    return redirect(url_for('heatmap', msg='🧹 Heatmap reset — all cells cleared!'))



#------------------ SETTINGS ROUTES ---------------------

@app.route('/settings')
def settings():
    tab = request.args.get('tab', 'customers')  # default to 'customers'
    customers = Customer.query.order_by(Customer.name).all()
    partners = Partner.query.order_by(Partner.name).all()
    return render_template('settings.html', tab=tab, customers=customers, partners=partners)







# --------------------- MAIN ---------------------
if __name__ == '__main__':
    ENABLE_FAKE_DATA = False  # ← Set to True if you ever want to load dummy data again

    with app.app_context():
        db.create_all()

    app.run(debug=True)
