# CL Paints Google Calendar sync

This is a one-way export from CL Paints to the company calendar, using Google's
Calendar API. Under Review and Awaiting Payment entries are tentative/free;
Accepted bookings are labelled Confirmed and reserve time. Each booking date
gets an entry, including overnight events. Dates use Europe/London with daylight
saving offsets. Setup/travel buffers and manually blocked time are not exported.

Changing a date or status updates its entry. Deleting a booking or changing it
outside these three statuses removes its exported entries. Marking an event
completed in the app retains its Accepted status and calendar history.
Unrelated Google events are never imported or edited. Edits to exported
events in Google are overwritten on the next sync. Customer names, venues and an
admin booking link appear in private calendar entries; internal notes, invoices,
signatures and contact details are not exported. No attendees or invitations are added.

## One-time setup on the live hosting service

1. In Google Cloud, select/create the company's project and enable Google Calendar API.
2. Open **Google Auth Platform → Branding** and configure the app as **CL Paints**.
   Use **Internal** audience if this is for members of your Workspace organisation.
   Otherwise select **External**, add the company Google account as a test user
   while developing, and complete any required publishing/verification for live use.
3. Under **Data Access**, add `https://www.googleapis.com/auth/calendar.events`.
   The Google account you connect must be an owner or writer with access to private
   event details on the selected calendar. Organisation OAuth access policies still apply.
4. Under **Clients → Create client**, choose **Web application** and name it
   **CL Paints Calendar**. Add the exact **Authorised redirect URI**:
   `https://YOUR-APP-HOST/admin/calendar/google/callback`.
   Use the same HTTPS host configured in app Settings as **Public app URL**.
   For local testing, register a separate localhost URI and configure the local
   Public app URL accordingly. Do not use an untrusted host.
5. Copy the OAuth client ID and client secret into the hosting environment:
   - `GOOGLE_CALENDAR_ID`: the exact company Calendar ID.
   - `GOOGLE_CALENDAR_CLIENT_ID`: the OAuth Web application client ID.
   - `GOOGLE_CALENDAR_CLIENT_SECRET`: its secret; never commit or paste into chat.
   - `SECRET_KEY`: keep the app's existing stable server secret. Do not replace
     it during setup if already configured.
   Calendar ID is found under Google Calendar **Settings → CL Paints → Integrate
   calendar**. Service-account keys are not used and no organisation policy needs
   to be disabled. A previously created service account is not needed by this flow.
6. Redeploy to install the declared encryption dependency. Open **Availability
   calendar → Google Calendar sync → Connect Google Calendar**. Sign in with the
   company account, grant calendar access and return to the app. The app checks
   write access without creating events. No access/refresh tokens are placed in
   browser cookies or shown on the page.
7. Choose **Preview changes**, review the counts, then **Sync to Google Calendar now**.

The refresh token is encrypted in BusinessSetting with a key derived from the
server `SECRET_KEY`. The web app and scheduled command must use the same secret
and database. Rotating that secret requires reconnecting the calendar. Backups
contain encrypted tokens; protect the database and environment together.

An External OAuth app left in **Testing** issues refresh tokens that expire after
seven days for Calendar access. Complete the appropriate production setup before
relying on unattended syncing. Revoking access or organisation policies can also
require reconnecting. **Disconnect calendar sync** removes the saved token and
stops subsequent syncs; it retains exported events. Revoke the app's permission
in the Google account's third-party connections settings to revoke the grant itself.

The app reads/writes only the configured calendar and marks its events with a
private application identifier stored in the existing BusinessSetting table.
Keep the production database backed up: this identifier prevents duplicate exports.
Do not run an independent local database against the same company calendar;
it would have a separate application identifier. Changing the target calendar
does not clear events from the old calendar; reconcile those before switching.
Changing Calendar ID requires reconnecting Google so calendar access is checked again.

## Automatic checks

Run this every five minutes using the hosting scheduler and the same production
environment/database as the web service:

```sh
flask --app app sync-google-calendar --apply
```

Omit `--apply` for a read-only preview of Google changes. A preview may initialise
the app identifier locally. No background scheduler is started by the web app.
Retain command output and alert on nonzero exits. Google updates aren't atomic;
if a connection fails midway, rerun to reconcile. Stable IDs prevent duplicate
events after a successful request whose response was lost. Changes appear after
the next successful sync, rather than immediately when a booking is saved.

The company calendar must remain private to appropriate staff. Calendar syncing
does not change booking status, send payment requests, or confirm a booking.

Official references:
- https://developers.google.com/workspace/calendar/api/concepts/sharing
- https://developers.google.com/workspace/calendar/api/v3/reference/events/insert
- https://developers.google.com/workspace/calendar/api/guides/extended-properties
- https://developers.google.com/identity/protocols/oauth2/web-server
- https://developers.google.com/workspace/guides/configure-oauth-consent
