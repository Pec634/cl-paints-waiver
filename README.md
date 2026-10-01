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

## Data handling
The app uses `DATABASE_URL` when configured and otherwise uses a local SQLite database. Booking and waiver submissions store personal information, signatures, and event details; protect database access and backups accordingly. Booking payment preferences are recorded, but the app does not process payments.

## Run it in VS Code
1. Open this folder in VS Code.
2. Open **Terminal → New Terminal**.
3. Run: `py -m venv .venv`
4. PowerShell: `.venv\Scripts\Activate.ps1`
5. Run: `pip install -r requirements.txt`
6. Run: `python app.py`
7. Open `http://127.0.0.1:5000`

## Booking form integrations
- Set `GOOGLE_MAPS_API_KEY` in the app environment to enable Google Maps Places address suggestions. Enable the Maps JavaScript and Places APIs, and restrict the key to the app's allowed website referrers.
- Phone numbers are validated with the `phonenumbers` package using the UK region unless an international prefix is entered.
- Referral codes can be added, verified, or bulk-imported from CSV on the admin Bookings page. Export the existing codes with `code`, optional `expires_at`, and optional `active` columns.
- Booking submissions only record a full-payment or 50% deposit preference. They do not process card payments. During review, admins enter one-way road miles for each event date; the first 10 miles per date are free, additional miles are £1 each, and the combined travel charge is capped at £50 per booking. Internal notes are admin-only.
- Client booking copies use the existing Resend integration. Configure `RESEND_API_KEY` and verify the `info@clpaints.com` sender before expecting confirmation emails; bookings are saved even if email delivery is unavailable.
- Admin password recovery sends a one-time reset link to `ADMIN_EMAIL`. Configure `ADMIN_EMAIL` and `RESEND_API_KEY`, verify the `info@clpaints.com` sender, and restart the app. Reset links expire after 30 minutes and can be used once.
