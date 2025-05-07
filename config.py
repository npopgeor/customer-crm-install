import os


from dotenv import load_dotenv
from utils import logger

# === Load environment variables from .env ===
load_dotenv()

# === Environment-derived constants ===
DEVICE_NAME = os.environ.get("DEVICE_NAME", "UNKNOWN_DEVICE")
ONEDRIVE_PATH = os.environ.get("ONEDRIVE_PATH")
DATABASE_PATH = os.environ.get("DATABASE_PATH")

if not ONEDRIVE_PATH or not DATABASE_PATH:
    raise RuntimeError("❌ Missing ONEDRIVE_PATH or DATABASE_PATH in .env.")
logger.info(f"📁 ONEDRIVE path: {ONEDRIVE_PATH}")
logger.info(f"🗃️ DATABASE path: {DATABASE_PATH}")

# === Derived paths and config constants ===
SKIP_FOLDERS = {"APP", "APP backup"}
DISCOVERY_ROOT = ONEDRIVE_PATH
BACKUP_SHARED_DIR = os.path.join(ONEDRIVE_PATH, "APP backup")
BACKUP_LOCAL_DIR = os.path.join(os.getcwd(), "instance", "backup")
UPLOAD_FOLDER = os.path.join(os.getcwd(), "uploads")
LOGO_UPLOAD_FOLDER = os.path.join(
    os.getcwd(), "static", "logos"
)  # avoid app reference here

SQLALCHEMY_DATABASE_URI = f"sqlite:///{DATABASE_PATH}"
SQLALCHEMY_TRACK_MODIFICATIONS = False

# === Heatmap columns ===
COLUMNS = [
    "Enterprise Switching",
    "Internet Infra",
    "DC Networking",
    "Enterprise Routing",
    "Security",
    "Wireless",
    "Compute",
    "Assurance",
    "Collab",
    "IOT",
    "Meraki",
]

# === Logging setup ===
CHANGE_LOG_FILE = os.path.join(ONEDRIVE_PATH, "APP", "change_log.txt")

os.makedirs(LOGO_UPLOAD_FOLDER, exist_ok=True)
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(BACKUP_LOCAL_DIR, exist_ok=True)
