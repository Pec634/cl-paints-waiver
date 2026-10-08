# CL Paints Waiver Module — VS Code Starter

This is the first safe development stage for the new Waiver module.

## What it includes

For the current form builder, booking features and setup instructions, see [Form builder guide](FORM_BUILDER_GUIDE.md).

Both portals have mobile quick links and menus that close with Escape or an
outside click. Admin **Needs attention** combines booking reviews, waivers
expiring within 30 days, unread booking conversations, pending change/cancellation
requests and recorded deposit/balance payments due today or earlier. The client
dashboard starts with **Your next steps** for unread conversations, missing contact
details and recorded payments due on accepted bookings.

Open **Messages** on an admin booking or **Booking messages** on the client's
booking detail to use the private conversation. Messages are stored in the portal;
email notifications are not sent for these conversations. Opening the thread
marks the displayed incoming messages as read; older messages remain available
through pagination. General Contact us enquiries and explicit booking change
requests continue to use their existing workflows. Restart the app to create the
new booking message table automatically; existing records are retained.

For the remaining portal features and how to use them, see
[Portal guide](PORTAL_GUIDE.md).

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
The app uses `DATABASE_URL` when configured and otherwise uses a local SQLite database. Booking and waiver submissions store personal information, signatures, and event details; protect database access and backups accordingly. Configured online payments use SumUp-hosted checkout, with successful payments verified and recorded by the app. Card details are entered on SumUp rather than in this app.

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
# SumUp invoices

From a booking's Payments page, choose **Attach SumUp invoice**. Create and send
the invoice in SumUp first; include the booking reference in its description.
Attach its invoice number, purpose (deposit, balance or full payment), amount,
due date and secure customer link. The client can open it from their booking.
Invoice numbers are unique across bookings to prevent accidental duplicate links.

This is an invoice-link workflow, not an API synchronisation. No SumUp API key
is required. Attaching an invoice does not charge a card, email the client or
mark it paid. Confirm receipt in SumUp, then record the payment in the booking
ledger using SumUp as the method and the invoice number in the internal note.
The existing booking update notification then reports the changed balance.

## Public-event waiver kiosk

Open Dashboard ? Business Tools ? Event waiver kiosk, select an open public event
and enter the staff PIN. The first launch sets a 4?8 digit PIN stored as a hash.
Customers complete the normal waiver without creating an account or verifying
their email. Confirmation emails use the existing waiver workflow. If they later
create an account and verify the same email, their waiver and members appear
in their portal. Customers are signed out immediately
after saving; the completion screen resets after 30 seconds, including when
reloaded. Only exiting needs the staff PIN. Five incorrect PIN attempts lock
exit controls for five minutes. Use the Full screen button on the kiosk screen.

To prevent browser navigation, device buttons or exiting full screen, configure
the device's OS kiosk mode or Guided Access. A website cannot enforce those
restrictions. Test email delivery and the complete flow on the actual event
connection/device before use. Kiosk setup requires an authenticated admin.


## Marketing campaigns

Open Dashboard > Business Tools > Marketing emails, or Settings > Email
configuration > Marketing campaigns. Save a subject and plain-text message,
review the preview and send a test before confirming the recipient list.
Draft campaigns support editable subjects, headings, inbox preview text, accent
colours, card or simple layouts, footer text and an optional HTTPS action button.
Upload up to four JPG/PNG/WebP images (2 MB each) using the existing Cloudinary
configuration. Images appear above or below the message, in upload order, with
an editable description for each upload. Images are embedded as hosted images,
not downloadable file attachments. The preview uses the actual email template;
send a test to check rendering in the recipient's mail app. Campaign content and
images are locked once its recipient list is confirmed.
Recipients are deduplicated by email and must have opted in on their latest
waiver. An unsubscribe always excludes the address from future marketing,
even if an older or subsequent waiver is opted in. Essential emails are separate.

Send remaining emails sends one recipient per request, with a pause between
requests. Keep the page open; pause or reopen the campaign to continue pending
recipients. Consent is checked immediately before sending. Accepted means the
existing Resend API accepted the request; inspect Resend for delivery/bounces.
Failed or interrupted (sending) attempts are retained and are not automatically
retried, to avoid duplicate emails. Test links are previews and change no consent.
No campaign sends automatically on creation, deployment or startup.

## Connecteam staff rota

Set CONNECTEAM_API_KEY in the server environment (local .env or Render's
environment settings), then open Dashboard > Business Tools > Staff rota.
Choose an active Connecteam schedule. The page reads up to 100 shifts for the
next 30 days and shows UK times. Accepted bookings have a Staff rota shortcut.
Each accepted booking date can be explicitly exported as one unpublished,
unassigned draft shift, with the booking reference, event times, venue and theme.
Assign staff and publish in Connecteam. No live shift is created by opening a
page, accepting a booking or running tests.

Export records prevent duplicate submissions. An uncertain/failed response is
marked check_required and blocked from automatic retry; inspect Connecteam
before resolving it. Booking changes are flagged against the saved export,
but changes and cancellations must be applied manually in Connecteam. This
initial integration does not automatically update/delete shifts or sync staff
names. API write access is only verified when an administrator exports a real
booking. Keep API keys out of Git.

## Event-day dashboard

Open Dashboard > Business Tools > Event day. It defaults to today's UK date,
with a date picker for other days. Event cards bring together kiosk launch,
waiver links, member lookup, moodboards and existing loyalty QR codes. Only
public events show waiver and loyalty tools; closed events cannot launch a
kiosk. Accepted booking dates include details, payments and staff-rota links.
Cancelled/nonaccepted linked events are excluded. Loyalty totals exclude
reversed visits; waivers are matched by their saved event name and date and
are explicitly not an attendance count. Loading the selected Connecteam rota
is optional and read-only, showing up to 100 shifts and assignment counts for
the selected UK day. This page never creates shifts or awards loyalty points.


## Forms, giveaway and scheduled offers

### Native forms (replaces the client Cognito links)

Open Forms & seasonal offers > Create and manage native forms. Create giveaway,
photo/video consent or seasonal booking drafts. Set actual rules/permissions,
optional UK opening and closing times and up to ten extra questions. Drafts can
be edited; unpublish before changing an existing form. Publish when ready.
Published/open forms appear in client and admin Rewards and seasonal Bookings.
No giveaway rules or photography permissions are guessed or auto-published.

Giveaway/media submissions require verified client sign-in. Giveaway entries are
limited to one per account per form, not guaranteed one per person. Media forms
require authority declarations and consent to the saved wording, accept one to
three JPG/PNG/WebP/MP4 files under 10 MB each, and store uploads in the database.
Photo submissions have a 32 MB request limit; the overall upload limit is 100 MB
to accommodate seasonal design uploads. Media downloads require the submitting
client or an authenticated, unexpired admin session; uploads are not public or
automatically published. Database backups include these private files.
Customers can view their submissions from Rewards; admins view entries from
the form editor. Every submission preserves its accepted wording and answers.
Consent withdrawal enquiries use Contact us with the submission reference.

Seasonal forms reuse the full booking form and save their additional questions,
title and wording in the booking's event_schedule. Requests appear in Bookings
and the native form's submissions view. Existing booking prices, promotions,
payment workflows and status notifications continue to apply. Native submissions
do not automatically import historic Cognito entries. Incident and collision
reports are now native admin-only forms. Screenshot-based draft templates are available for Quarterly
VIP Give-away, Photography consent and Halloween promotion. Review dates and
travel wording before publishing: the supplied giveaway refers to Doncaster,
while the portal business address is London. The editor supports text, textarea,
number, date, checkbox and select questions. Photo templates collect repeatable
participant permissions, event details, acknowledgements and a typed signature.
The giveaway template captures age and eligibility declarations and a separate
Yes/No marketing preference; the latest recorded preference is used for marketing
recipients, and an unsubscribe continues to override opt-ins. Seasonal bookings
accept up to six private JPG/PNG/WebP design images, at most 15 MB each, with
admin-only downloads from their native submissions view.

### Legacy external forms and promotions

### Local client portal preview

To preview without sending an email verification code, set `FLASK_DEBUG=1` and
`CLIENT_LOCAL_PREVIEW=true` in your local `.env`, restart the app, and visit
`http://127.0.0.1:5000/client/login`. Choose **Preview portal locally**. This
creates a separate `portal-preview@example.invalid` test account in your local
database; it does not sign in as an existing customer. The option requires debug
mode, a loopback connection and a localhost host, and is disabled whenever the
`RENDER` environment variable is present. Do not enable these flags on the server.
Preview form submissions still write to the local database. Remove the preview
flag and restart when finished.

Client and admin Rewards now display published native giveaway and photo/video
consent forms. Native staff incident and road-traffic reports are available from
Dashboard > Business Tools > Forms & seasonal offers. Reports have server-side
required-field validation, CSRF protection, immutable submitted details, typed
signature fields and private evidence downloads. Up to six JPG/PNG/WebP images
are stored per report, at most 15 MB each. Reports and media require admin access;
database backups include the evidence. The road collision fields are a new
template rather than a transcription of the original form. Historical submissions
stay in Cognito Forms and are not imported automatically. Older external form
definitions are retained, but client seasonal links now use native forms.

Scheduled hourly discounts apply to new internal booking requests submitted
within the configured UK-time start-inclusive, end-exclusive interval. The
largest active saving wins; discounts do not stack and rates never fall below
zero. The saved quote stores the promotion and effective hourly rate. Existing
bookings keep their prices, travel and pitch-fee rules remain, and external
Cognito forms require separate pricing configuration. An estimate opened
before an offer starts or ends is recalculated on submission.


The studio Community gallery is available to signed-in clients at
`/client/community-gallery`. Sharing is optional: submissions begin as pending
and show a chosen display name or "Anonymous painter", never the account email.
Admins review submissions and reports at `/admin/studio-gallery` (also linked
from the dashboard). Creators can withdraw their own designs; favourites and
reports are account-scoped. PNG photographs are validated, bounded, and stored
in the application database alongside account ownership and moderation status.
Database backups therefore include gallery images. Restart the application to
create the three new gallery tables through the existing `db.create_all()` setup.
No historical browser-saved designs are uploaded automatically. Studio sharing
uses supplied templates and the illustrated character; there is no photo-upload
control. Admins should inspect the image, title and display name before approval.
The separate local design gallery still saves only on the current browser.
