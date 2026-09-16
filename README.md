# CL Paints Waiver Module — VS Code Starter

This is the first safe development stage for the new Waiver module.

## What it includes
- `/waiver` customer journey
- `/admin/waivers` admin prototype
- Liability Statement screen
- view-only Mood Board screen
- 1–4 people wording
- Responsible Adult screen
- Consent / T&Cs acknowledgements
- optional marketing permission
- signature placeholder
- admin Open / Closing Soon / Closed control

## Important
This version deliberately does **not** connect to the live PostgreSQL database, save customer information, alter the Referral System, replace Cognito, send emails, or store signatures.

## Run it in VS Code
1. Open this folder in VS Code.
2. Open **Terminal → New Terminal**.
3. Run: `py -m venv .venv`
4. PowerShell: `.venv\Scripts\Activate.ps1`
5. Run: `pip install -r requirements.txt`
6. Run: `python app.py`
7. Open `http://127.0.0.1:5000`

Next stage: wire the approved interface to a proper PostgreSQL waiver schema and migrations, while keeping the current live systems untouched.
