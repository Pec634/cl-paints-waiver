# Phone notification setup

Admins and clients open **Notifications → Phone notifications**, select categories,
and enable them on each device. Browser permission is requested only after tapping
the button. Preferences are stored per device and can be changed or disabled there.
On iPhone/iPad (iOS/iPadOS 16.4+), add the portal to the Home Screen and open it from
that icon first. Production needs HTTPS. The service worker only handles push; it
does not cache private portal pages.

## Deployment

1. Install `requirements.txt` and restart the application to create the two new
   database tables using the existing startup schema setup.
2. Run `.venv/Scripts/python.exe -m flask --app app push-keys` once. This creates
   `instance/push-private.pem` and `instance/push-public.txt`. Neither file is
   committed. Retain these keys securely across deployments; rotating them makes
   existing subscriptions unusable.
3. In the hosting environment set `VAPID_PUBLIC_KEY` to the contents of
   `push-public.txt`, `VAPID_PRIVATE_KEY` to the absolute path of the private PEM
   file (or its PEM contents), and `VAPID_SUBJECT` to a monitored contact such as
   `mailto:your-address@example.com`. Do not expose the private key to browsers.
4. Restart the web application and run **one** continuous worker alongside it,
   using the same environment, database and private key:
   `python -m flask --app app push-worker`.
   A scheduled job can instead run `python -m flask --app app push-worker --once`
   frequently. Run one worker/job at a time to avoid duplicate deliveries.
5. Enable notifications from an actual phone on the HTTPS site. Create a booking,
   send messages both ways, change its status, and record a payment. Verify correct
   recipients and tapping alerts returns to their authenticated portal. Real phone
   delivery has to be checked on the deployed site; automated tests mock providers.

When credentials are absent, the notification page explains that server setup is
required. No external notification account or paid notification service is needed;
the browser's push provider handles delivery. Network access to those providers is
required on the server.

## Alerts

- **Bookings:** new requests for admins and confirmation of receipt for clients;
  client booking updates, change/cancellation requests and decisions; proposed date
  changes and responses.
- **Messages:** only the other party receives a new booking-message alert.
- **Payments:** payment/refund ledger entries for both parties; new invoices for
  clients. An invoice notification does not mean money has been received.
- **Updates:** new client enquiries for admins, rewards updates for clients, and
  event feedback requests/responses.

Notifications show a short title and portal link, without names, payment amounts,
addresses or message bodies on the lock screen. Browser subscription endpoints and
encryption keys are private database records. A shared device is linked to the
currently signed-in account only when that user explicitly enables/saves settings;
that action clears pending notifications belonging to the previous account.
Turning off notifications disables the server subscription and clears pending
deliveries. Devices whose endpoints expire are disabled automatically.

Alerts are queued in the same database transaction as the saved change. Rolled-back
changes do not send alerts, and duplicate message/payment submissions keep existing
idempotency protections. Deliveries retry up to five attempts with delay; persistent
failures are discarded. Browser settings, network conditions and operating-system
restrictions can delay delivery; the notification centre remains the activity record.
CSV/XLSX/PDF imports do not notify clients or admins. Timed event/deposit reminders
are not part of this push implementation.
