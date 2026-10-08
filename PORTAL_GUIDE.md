# Admin and client portal features

## Importing records

Choose **Imports** in the admin sidebar. Download a client or booking CSV template,
or upload CSV/XLSX with your own column names, then match the columns and review
the preview. Nothing is added until you select rows and confirm the import.
Existing clients and matching bookings are skipped; existing records are not
overwritten. Repeated original source references are also detected for bookings.

Files allow up to 500 data rows, 60 columns and 5 MB. Use UTF-8 CSV or the first
worksheet of an XLSX file. Replace formulas with values. Dates accept YYYY-MM-DD
or DD/MM/YYYY, and times use HH:MM. PDF, scanned documents and older XLS files are
not supported. This first version imports one event per booking row; use the
normal booking workflow for multi-date bookings.

Client rows require email, first name and surname. Booking rows additionally
require date of birth, event date, start and finish times, venue and event name.
Optional status defaults to Under Review, setting to Private and estimates to
zero. Imported estimates are not payments received. No notification emails or
consent confirmations are created; original signatures may be copied but remain
unverified. Imported clients still verify their email when signing in.

Review accepted bookings carefully because they reserve calendar space. Import
previews are private to the uploading admin session, expire after 24 hours, and
their staged contents are cleared when imported or when expired batches are
cleaned up on the next visit to Imports. Import receipts remain for duplicate
protection. Install the updated requirements for XLSX support.

## Notifications and next steps

Admins can open **Notifications**, **Search all records** and **Calendar** from
the toolbar on admin pages. Clients have **Notifications** in the portal menu.
The notification centre combines recent bookings, general enquiries, booking
messages, payments, date proposals, form submissions (admin only) and feedback.
Filter by category, new updates or actions needed. **Mark current updates seen**
marks the updates loaded on that visit; it does not complete outstanding actions
or read booking conversations. The centre shows recent records; each booking
retains its full timeline.

Admin **Needs attention** remains at the top. Next steps also include approaching
confirmed events within seven days, proposed date decisions, unreviewed booking
changes and feedback requests. Payments only become due actions when a recorded
due date has arrived and an accepted booking still has money outstanding.

On phones, clients can go directly to Home, Bookings, Payments and Waivers.
**Payments & invoices** collects the client's own booking balances and invoice
links. The full menu retains Help, Account, Rewards and other tools.

## Activity and date changes

On an admin booking, choose **Activity & date changes**. Clients see their
timeline on the booking detail page. It includes the request, detail changes,
payments, messages, change/cancellation decisions, proposals and follow-up.
New booking changes record the acting client, shared admin identity or system.
Historical changes cannot recover identities that were not originally recorded.
Internal notes and company signature changes are logged for admins only.

Choose an event day, a replacement UK start time and a reason to propose a new
date. The existing duration, venue and recorded costs are retained. The proposed
time must avoid confirmed bookings, unavailable periods and configured buffers,
including other days of this booking. A proposal expires after seven days and
does not reserve the new time. The original booking remains unchanged until the
client accepts from their booking page.

Acceptance checks ownership, the proposal's expiry, the current booking details
and availability again. Changed or expired proposals require a fresh proposal;
new conflicts leave the original dates in place. Clients can decline, and admins
can withdraw a pending proposal. Accepted changes update the selected event day
and any linked public-event date, preserving form and pricing metadata. Changes
to duration, venue or price continue to use the existing change-request workflow.

## Completion and feedback

After all event times have passed, use **Mark event completed**, then
**Request feedback**. Completion is recorded separately from the existing booking
status. Feedback requests appear in the client portal; the request also attempts
one email using the existing email configuration. Failed email attempts can be
retried. This is an explicit admin action, not an automatic scheduled campaign.

The client can submit one private 1–5 rating and optional comments. Feedback is
visible only to the client and admins. **Book another event using these details**
reuses editable event and profile details, clears dates and requires a fresh
signature, consent, pricing selection and review. It does not submit a booking
automatically or reuse promotions.

## Search, accessibility and recovery

Global admin search covers names, email addresses, phone numbers, booking
references, waiver references, forms and submissions. Results are bounded to
20 per category; refine broad searches. Opening a submission shows that response.

**Display settings**, below each page and linked from the client's Account menu,
controls text size, animation and contrast. Preferences are saved locally in the
browser and apply across both portals. Reset restores defaults, including the
device's reduced-motion preference. Keyboard users have a Skip to content link,
focusable controls and Escape support for mobile menus.

Recovery pages explain outdated forms, missing records, permission errors,
conflicting saves, large uploads, rate limits and server errors. HTTP status codes
and API error responses are retained. Failed submissions are never retried
automatically.

Restart the app after updating. The existing startup creates the new audit,
proposal, follow-up and notification-read tables without replacing existing data.
The features use the existing authentication, CSRF, booking and payment services.
