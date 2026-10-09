# Admin and client portal features

## Unified communications workspace

Open **Notifications & messages** in the admin sidebar. The shared section menu
is available on activity, conversation, history, template, campaign and configuration
pages. Activity combines notifications and outstanding actions. Messages offers
client messages, unread messages, sent admin replies and general enquiries; open
a booking conversation to reply or manage an enquiry directly in that section.
Viewing message lists does not mark them read. Sent booking messages are preserved
in their conversation history rather than edited retroactively.

Email history searches notification records and campaign recipients by sending
status. Notification records retain update details, not snapshots of the historical
email layout. Provider acceptance does not prove inbox delivery; client preferences
can also explain a notification that was not sent. Older acknowledgements and login
verification emails are not in this history. Campaign content remains on its campaign
record. Phone alerts retain pending queue entries but not a historical delivery log.

Email templates & layout contains the existing live composer and uploaded media.
Configuration contains admin phone preferences and automatic-event-reminder settings.
Phone keys, the push worker, reminder scheduler and Resend credentials still require
the deployment configuration described elsewhere in this guide. Client preferences
and consent continue to apply. General Settings retains business, pricing and account
controls; email and reminder controls link into the communications workspace.

## Email images, attachments and links

Open **Settings → Email configuration → Images, documents & links**. Add a label
and choose booking updates, reward notifications or both. Images (PNG/JPEG/GIF)
are embedded below the heading; documents (PDF/DOCX/XLSX/PPTX/UTF-8 TXT, or image
files) are downloadable email attachments; labelled HTTPS links appear below
the email content and are also included in the plain-text version.

Preview the relevant saved layout before sending. The preview serves files through
admin-only routes, while actual emails carry file content, including inline image
attachments. Maximum 2 MB per file, 5 MB of files overall and 12 items. Remove an
item to stop including it in future emails, or remove and re-add it to replace it.
Use general material appropriate for every recipient in the chosen email group.
These additions apply to the existing configurable booking-update/reward layouts,
not verification emails, marketing campaigns or booking acknowledgement emails.
Restart the application to create the new email-media table. No new service or
credentials are required beyond the existing Resend configuration.

Email configuration uses a composer layout with a template menu, subject and message
editor, insertion tools and a saved-email preview. Select Booking updates or Rewards
to edit that template; insert client name, reference and update details at the cursor.
The image/file/link toolbar opens the media panel with the selected template and
item type already chosen. Shared design and media settings expand when needed.
The live preview updates while editing subject, content, shared design and layout.
Saving does not send an email. The preview appears below the editor on narrow screens.

**Custom layout** lets each template choose width, spacing, font, text size, line
spacing, corner rounding, colours, alignment and portal-link wording. Move blocks
up/down to place images, links and document labels around the heading, message,
portal link and footer. Images have percentage width, alignment and captions;
links can appear as text or buttons. Save content & layout persists the current
template, layout and shared heading/footer/accent settings. Shared design changes
apply to both email groups; block order and custom styles are separate per group.
Live previews use sample data and the same renderer as actual notifications. An
invalid value leaves the last valid preview visible and displays an explanation.
Previewing alone does not save changes or send emails. Save before leaving the
page or uploading another item. Files are managed in the attachment panel; after
adding a file its block becomes available for placement.

## Admin client profiles

Every client account has a stable account number such as `CL-A-0001`, derived
from its retained account ID. Existing accounts receive the display number without
a data migration. Find it on the Clients cards and profile header; search the full
number in Clients or Search all records. Clients offers 24 accounts per page,
contact cards, address search and direct profile links. Enquiry replies are managed
in the communications hub; the client list shows the five most recent enquiries.
Referral-code linking expands only when needed.

The client dashboard reference panel uses smaller text and tighter spacing for
waivers, loyalty, referrals and recent booking references. Extra waiver/member/code
rows expand on demand; links still open all records. Profile navigation uses aligned
section buttons and adapts to a two-column grid on phones.

Open a client name in **Clients** or a client result in **Search all records**.
The private profile shows contact details, account creation date, booking counts,
review requests, unread client messages, upcoming accepted events and payment totals.
The outstanding summary includes accepted bookings only; cancelled and declined
booking arrangements remain available in the Payments section.

Use the section links for paginated bookings, payment ledgers and invoices, signed
waivers, conversations, current loyalty members and referral codes, or admin-only
notes. Booking links open the existing activity timeline and actions. Viewing the
profile does not mark conversations read. History is linked by account email;
changing an account email does not merge records held under older addresses.
Transferred members appear under their current custodian.

Admin notes are append-only and timestamped. They are never sent as notifications
or shown in the client portal. Dates of birth, signatures, login codes and payment
card information are not shown in the profile overview. Contact changes remain in
the existing client account workflow. Restart the application to create the new
admin-client-note table without replacing existing records.

## Importing records

Choose **Imports** in the admin sidebar. Download a client or booking CSV template,
or upload CSV/XLSX with your own column names, then match the columns and review
the preview. Nothing is added until you select rows and confirm the import.
Existing clients and matching bookings are skipped; existing records are not
overwritten. Repeated original source references are also detected for bookings.

Files allow up to 500 data rows, 60 columns and 5 MB. Use UTF-8 CSV or the first
worksheet of an XLSX file. Replace formulas with values. Dates accept YYYY-MM-DD
or DD/MM/YYYY, and times use HH:MM. Older XLS files are not supported.
This version imports one event per booking row; use the
normal booking workflow for multi-date bookings.

PDF uploads support selectable text, labelled details, simple tables and known
filled form fields. Open the extracted page text alongside the editable records,
correct missing or misidentified details, and save corrections before confirming
the import. Extraction runs locally; documents are not sent to an external service.
PDFs can contain up to 20 pages within the 5 MB upload limit. Unlock protected PDFs
first. Scanned PDFs need OCR (text recognition) and must be saved as searchable
PDFs before uploading; automatic OCR is not included.

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
protection. Install the updated requirements for XLSX and PDF support.

## Notifications and next steps

Phone push controls are available in each portal's notification centre. Choose
bookings, messages, payments and other updates per device. Hosted setup needs HTTPS,
VAPID keys and one delivery worker; see [Phone notification setup](PHONE_NOTIFICATIONS.md).

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

Portal organisation
-------------------
Admin navigation groups bookings/events, clients/rewards, communications and
business settings. The current page's group opens automatically. Without
JavaScript the original navigation links remain available.

The Bookings list can save its selected filter on the current browser/device.
Saved filters contain filter choices only and can be removed from the same page.
Admin tables present labelled cards on phones; desktop tables remain available.

Client booking pages show event details and progress before payments, with
activity history later. Both client booking details and the admin booking
activity page offer section shortcuts and share the booking progress display.
The existing notification centre already links updates to relevant records.

Account, preference, booking and profile editing forms warn before leaving with
unsaved edits. Browser confirmation wording is controlled by the browser.
Empty dashboard payment/change panels are hidden until relevant records exist.
The dashboard's request and reward counts remain visible below the welcome area.

Public website and studio
-------------------------
The public website is at /, with /services, /about, /gallery and /contact.
Pricing comes from General settings; login review settings also supply the public
review carousel. Giveaway announcements are editable in General settings and
currently available giveaway forms appear automatically.
The Face Paint Studio is now at /face-paint-studio and is available to guests.
The legacy client studio URL redirects to it. Sharing, favourites and community
interactions continue to require an account and existing CSRF checks. Guest
painting, downloads and browser-local studio progress remain available.

## Signed photo uploads and website library
Clients use My events > Upload photos to submit up to three images with per-photo identities, descriptions for group photographs, a responsible person and a drawn signature. Review images in Business settings > Photo library before approval. Public captions are separate from private identities. Select website placements or choose an approved photo as an event story cover under Event stories. Legacy photography form images also enter the library; a signed authority record is required for approval. Clients can withdraw a release: website photo links and covered stories then stop displaying. Remove social media and printed copies separately when a withdrawal arrives. Database backups now also contain private photographs and releases.