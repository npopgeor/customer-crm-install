# CRM Web App – Setup Guide for Mac

This package includes everything needed to run the CRM application locally.

---

## ✅ 1. Installation (One-Time Setup)

Open Terminal, go to the extracted folder, and run:

    ./install_crm.sh

This script will:

- Install Python 3 using Homebrew if it's not installed.
- Set up a Python virtual environment.
- Install all required Python libraries.
- Locate your OneDrive folder named:
  "Gary Bedol (gbedol)'s files - SP Accounts FY25"
- Create necessary folders and environment variables.

---

## 🚀 2. Starting the App

To start the app in the background:

    ./start_crm.sh

The app will be available at:

    http://localhost:5000

Logs are saved in `crm_log.txt`.

---

## 📁 Included Files

- `app.py` — the main Flask application
- `requirements.txt` — Python dependencies
- `install_crm.sh` — installation/setup script
- `start_crm.sh` — app launcher
- `templates/` — Jinja HTML templates
- `uploads/` — file upload directory (created automatically)
- `static/` — static assets (CSS, JS, optional)

---

## 💡 Tip

To stop the app running in the background:

    ps aux | grep flask
    kill <PID>

Or just reboot 🙂

---
