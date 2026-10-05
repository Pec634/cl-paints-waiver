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

## Client portal

- `/client/signup` creates client accounts after email verification; `/client/login` signs returning clients in using email codes. Configure `RESEND_API_KEY`, a verified `info@clpaints.com` sender and a stable `SECRET_KEY` on the server. Codes expire after 10 minutes, permit five attempts and are single-use. Requests have email/IP rate limits and a 60-second resend cooldown. Plaintext codes are never stored or logged. Client sessions expire after eight hours.
- Clients can view their dashboard, bookings, rewards, contact details and account. Existing bookings are matched to verified email addresses. Client booking submissions always use that verified email, even if a submitted form tries to supply another one. Internal notes, company signatures and other clients' records are excluded.
- Admin → Clients lists verified accounts and the latest 50 enquiries. Link existing referral codes to their verified owners there; names alone are not sufficient to establish ownership. Referral status and redemption remain controlled in Rewards.
- Contact enquiries are saved for admin review and emailed through Resend to the contact email in Settings. Notifications include the client's contact details, message and a link to the admin record. Email delivery failure does not discard the saved enquiry. The client portal does not process payments. Email changes and reassignment of existing reward owners require admin assistance.

## Public-event loyalty and member transfers

## Day-to-day business tools

- **Bookings → Payments & deposit** records payments/refunds, deposit and balance due dates, and calculates outstanding balance or overpayment credit. Entries are retained rather than deleted. Each submission has an idempotency token. Internal payment notes are hidden from clients. Client booking pages show payments and receive the standard highlighted booking-update notice.
- **Bookings → Availability calendar** displays a UK-time month view and flags possible overlaps, including unavailable blocks. Settings configures a buffer on each side of bookings for setup/travel (default 60 minutes). Pending requests are shown separately from accepted reservations. Warnings are advisory; review them before accepting a booking.
- **Clients → Recent enquiries** supports new/replied/resolved status and saved replies. A changed reply is emailed once and visible on the client's Contact page. Unchanged replies do not resend.
- **Events → Loyalty QR & visits** allows a reasoned reversal of an accidental point/free-paint award. Reverse later visits first. The original visit and reason are retained, and the corrected event cannot be rescanned for another point. Free-visit reversals restore three points.
- **Settings → Email configuration** has previews of saved booking/reward templates plus the latest 100 sending attempts. Accepted for sending is not confirmation of inbox delivery; use Resend's dashboard for delivered/bounced outcomes.
- **Settings → Availability & reminders** configures reminder lead time and the HTTPS public app URL. Run `.venv/Scripts/python.exe -m flask --app app send-booking-reminders` locally for a dry run. On the deployed host, schedule `flask --app app send-booking-reminders --send` daily against the **same production database** and Resend credentials. Reminders are only for accepted events in the next configured number of days, include time/address/balance/setup guidance, and are sent once per booking/event date. Failed sends can retry; a ten-minute claim prevents concurrent workers from duplicating attempts. An external scheduler is required; no reminder scheduler is enabled automatically. A separate Render cron service needs a shared PostgreSQL database; it cannot use another service's local SQLite file.
- **Settings → Backup & recovery** downloads an integrity-checked SQLite snapshot containing all database records. PostgreSQL uses provider backups/recovery instead. Backups contain private data and must be stored privately. Cloudinary images, environment secrets, and external files are not included in a database snapshot.
- To validate a SQLite backup: `python restore_database.py --backup "path/to/backup.db"`. To restore, first stop every app process, then run `python restore_database.py --backup "path/to/backup.db" --database "path/to/current.db" --restore`. The utility saves an intact copy of the previous database, then restores and verifies the backup. Test on a temporary database first. The tool does not restore PostgreSQL or overwrite a running service through the web UI.
- Automated tests exercise signup/verification, booking privacy and updates, waivers, QR eligibility, per-member rewards, transfers, payment/refund balances, enquiry replies, reminders and synthetic backup recovery. Live email receipt and phone-camera QR scanning still require a deployed end-to-end test.

### Loyalty details

- Booking detail pages show the progress tracker and unreviewed customer-facing changes, including travel charges and revised estimates. Admin saves send one email when visible values change; internal notes alone do not send emails. Clients can acknowledge the specific displayed updates. Delivery failures leave the booking and change history saved.
- Settings → Client notification emails controls subjects, message bodies, heading/footer, accent colour and card/letter layout for booking updates and referral/loyalty notifications. Supported placeholders are `{name}`, `{reference}`, `{details}`; HTML is escaped and destination links are supplied by the app. Verification-code and initial booking-receipt emails keep their existing templates.
- Referral linking, referral usage, earning/redemption and loyalty points/free-paint claims generate customer notifications and an email attempt. Repeat scans and unchanged referral statuses do not send duplicates. Recent notifications are visible on the client dashboard; each member's loyalty ID and points are visible on My account.

- Admin → Events → Loyalty QR & visits generates a local SVG QR code. Codes only work for open/closing-soon public events on their UK event date; private booking days are rejected. A scan redirects through email login and returns the customer to that event.
- Customers select members under their current responsibility with valid waivers. Only selected members get points; each persistent member ID can claim once per event. Awards occur immediately after scan submission. Three points unlock that member's fourth scanned visit: choose a design from the event moodboard, claim one free paint and reset to zero. The free visit itself does not award a point. Staff can inspect the event's claim history and chosen designs.
- Rewards shows per-member balances. My waivers displays signed records matched to the verified account email, including participants, signature, declarations and the original terms. Historical signed records are preserved; archived, expired and superseded waivers cannot qualify a current member for loyalty.
- The current responsible person initiates a member transfer to an existing verified client account. The recipient receives a hashed, single-use, ten-minute approval code (five attempts), signs in and accepts using their own valid waiver reference and responsibility declaration. The member's original ID, waiver and loyalty history are retained. Current responsibility is stored separately and completed transfer records form an audit trail. No member deletion occurs.
- Loyalty uses new additive tables created at startup; install the updated requirements (`qrcode`, `tzdata`). Existing participants on different signed waivers are distinct IDs; the app does not merge people by name. Live email delivery and event QR scans must be checked after deployment.
