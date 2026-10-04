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

## Reports

- Open Reports in the admin navigation for booking trends and outcomes, event types, waiver and participant trends, participant age bands, referral milestones, booked hours and estimated accepted booking value.
- Filters support this month, the last three calendar months, this year or custom dates. Requests are grouped by submission date; waivers by signing date; workload by accepted event date. Referral cohorts use the original attended event date, with milestones counted through the selected end date.
- CSV exports contain aggregate totals without client names, emails or street addresses. Participant counts describe records on waivers, including repeat attendance, rather than unique people.
- Client locations group addresses by UK outward postcode district, using each email's latest address in the period for client counts. Switch to Event venues to compare where events take place. Missing postcodes are flagged.
- Select “Map new postcode districts” to fetch and cache district coordinates from [Postcodes.io](https://postcodes.io/docs/api/find-outcode/). Only outward postcode districts are sent. The map uses [Leaflet](https://leafletjs.com/examples/quick-start/) and OpenStreetMap tiles; no Google Maps key is needed. Each refresh handles up to 10 districts, and area totals remain available if the map or lookup provider is unavailable.

## Booking configuration
- Set `GOOGLE_MAPS_API_KEY` in the app environment to enable Google Maps Places address suggestions. Enable the Maps JavaScript and Places APIs, and restrict the key to the app's allowed website referrers.
- Phone numbers are validated with the `phonenumbers` package using the UK region unless an international prefix is entered.
- Rewards uses the standalone referral scheme: unique five-character codes, 12-month validity from the original attended private booking, attendance validation to earn 30 minutes free face painting, and one-time redemption. Earned rewards do not expire. Import the original active, earned and redeemed text files through Rewards → Import existing data; duplicate codes are skipped. Booking codes are case-sensitive and verified against active referrals, with attendance confirmed separately by an admin. Waiver references remain consent identifiers rather than referral codes. No automatic price adjustment is made when a referral is submitted.
- Booking submissions only record a full-payment or 50% deposit preference. They do not process card payments. During review, admins enter one-way road miles for each event date; the first 10 miles per date are free, additional miles are £1 each, and the combined travel charge is capped at £50 per booking. Internal notes are admin-only.
- Client booking copies use the existing Resend integration. Configure `RESEND_API_KEY` and verify the `info@clpaints.com` sender before expecting confirmation emails; bookings are saved even if email delivery is unavailable.
- Admin password recovery sends a one-time reset link to `ADMIN_EMAIL`. Configure `ADMIN_EMAIL` and `RESEND_API_KEY`, verify the `info@clpaints.com` sender, and restart the app. Reset links expire after 30 minutes and can be used once.

## Settings

- Business details appear on the public booking form. Configure the hourly rate, minimum event duration and maximum dates per request (up to 10), plus free travel miles, the additional mileage rate and booking travel cap.
- New requests store their pricing and travel rules. Later changes do not recalculate existing booking estimates or replace their saved travel rules. Older requests without a settings snapshot retain the original travel defaults.
- Admin account changes require the current password. New passwords must be 12–128 characters. The saved recovery email overrides `ADMIN_EMAIL`; Resend configuration is still required for recovery messages. Account changes invalidate outstanding password reset links.

## Transfer referral records to the live app

Run `python export_rewards_transfer.py` locally to create `instance/rewards-transfer.json`. The file is excluded from Git and contains names, codes, dates, reward status and single-use history. After deploying the code, sign into the live app and open Rewards → Import existing data → Transfer from the development app. Upload that JSON file. Existing live codes are preserved and repeated imports do not create duplicates. Database files, admin credentials, waivers and booking personal details are not exported.
