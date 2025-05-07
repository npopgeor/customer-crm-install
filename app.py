
# IMPORTS
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
)
from extensions import db
from utils import (
    daily_backup_if_needed
)



app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "fallback_dev_secret")


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
