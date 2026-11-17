# CL Paints staff POS for Android

The `pos` module builds a separate **CL Paints POS** app for Android 8 or newer.
It opens the authenticated staff till at `https://my.clpaints.com/admin/pos`.
Deploy the server changes and restart it before using the app; startup creates
the `pos_sale`, `pos_product` and `pos_refund` tables and upgrades existing till
records. The existing client app remains a separate application.

## Included

- Staff login using the existing admin account and session timeout.
- Search existing waivers by adult name, participant name, email or waiver reference.
  Results show participants, event, expiry and status. Archived waivers are excluded;
  expired or otherwise invalid waivers cannot be linked to a sale. Linking consent
  does not record attendance, award points, or extend consent.
- A shared item library with saved GBP unit prices, search and tap-to-add tiles.
  Use **Manage items & saved prices** to add, rename, reprice or remove items.
- Repeated taps increase basket quantities. Basket quantities and unit prices can
  be edited for individual sales, and lines can be removed. Custom items remain
  available. Library changes do not alter existing baskets or completed sales.
- Cash received recording, recent sales, and sale details with an optional waiver link.
- Cash payment opens inside the basket: enter the tender, check live change, then
  complete the sale. The till retains a confirmation with the change to hand back.
- Optional email receipts: select **Customer wants an email receipt**, confirm the
  email address, and complete payment. Linked waiver emails are prefilled without
  opting the customer in. Cash receipts send when recorded; card receipts send
  only after verified payment. Receipt status and send time are saved on the sale;
  failed sends can be retried from the saved sale or cash confirmation. These use
  the portal's existing email service and outgoing-email history.
- Paid sales can award loyalty directly to the individuals being painted. Link
  their waiver, select today's open public event and tick the relevant members.
  Individual waivers select their sole member automatically. Cash completion or
  verified card payment records the point in the existing loyalty visit ledger;
  QR check-ins and other sales cannot award a second point at that event. Balances
  remain capped at three; free paints still use the existing redemption flow.
  Till and event loyalty logs link the award back to the sale. A member without
  a portal account is linked to an account under the waiver's responsible email.
- Searchable, paginated sale history stores items, unit prices, total, tender/change,
  payment status and optional waiver/participant links. Search by sale number,
  transaction reference, waiver reference, email or names. Client profiles and
  waiver details link to the matching till history. Customer names at sale are
  retained even when the linked waiver is subsequently edited or archived.
- Solo Lite payment handoff, persistent pending sales and server verification.

The app needs an internet connection. Till sales remain separate from booking
payments, invoices and stock. Confirmed sales and refunds now feed daily handovers
and cash balances. Choose the trading event at checkout to allocate transactions
to its booking cash-up. Enter only additional non-POS takings in the manual fields;
the linked POS figures are included automatically. Unallocated sales still appear
in the daily handover. Saved handovers and cash-ups retain their financial and item
snapshots; later transactions require a new handover revision or cash-up correction.

Open a saved paid sale to refund all or selected remaining item quantities. Refunds
use the original unit prices and payment method, require a reason, and retain their
time, operator, items and status. For cash, confirm that the money was returned.
For cards, the server verifies the original merchant transaction then requests the
refund through SumUp. The API key must have refund permission. If a response is
lost, use **Check refund with SumUp**; an unresolved refund blocks another request.
Only confirmed refunds reduce takings, on the UK date the refund is recorded.
Failed and unconfirmed transactions remain visible in the daily transaction log.

Daily handovers, event cash-ups and saved printable reports include cash/card
sales, cash/card refunds, net takings and a breakdown by item and original unit
price, showing quantities sold/refunded and monetary totals. Refunds do not
automatically reverse loyalty history; use the existing event loyalty correction
workflow when an award also needs correcting.

There is no receipt printer integration, offline queue or Play Store release yet.

## SumUp configuration

Configure these **on the server**, outside Git:

```text
SUMUP_API_KEY=<key with transaction read access for the intended merchant>
SUMUP_MERCHANT_CODE=<CL Paints merchant code>
SUMUP_POS_AFFILIATE_KEY=<affiliate key registered to this Android app ID>
SUMUP_POS_APP_ID=com.clpaints.pos.preview
```

The debug APK uses `com.clpaints.pos.preview`; release uses `com.clpaints.pos`.
Register the matching ID and update the server setting before switching builds.
Only the affiliate key is passed to the device; the API key stays on the server.

Install SumUp's Android app on the same device, sign into the CL Paints merchant
account, and pair the Solo Lite in SumUp. Confirm the merchant and GBP currency
before use. The reader connects to SumUp over Bluetooth; it does not use Solo's
Cloud API. This initial version uses Payment Switch to fit the existing WebView
and Gradle setup without adding the reader SDK and its newer toolchain. SumUp no
longer actively develops Payment Switch and recommends the native SDK for new
native integrations; migrating to that SDK is a future integration step.

Create a card sale, tap **Prepare SumUp payment**, then **Open SumUp**. Finish
payment in SumUp. On return tap **Check payment with SumUp**. A callback alone
never marks a sale paid: the server checks the merchant-scoped transaction's
reference, successful status, currency and exact amount. A payment launches only
once from the sale; Android also remembers launched references. When interrupted,
declined or cancelled, inspect SumUp before creating another sale. Reopen pending
sales from Recent sales to retry verification, including after an app restart.
If the launch page is lost before opening SumUp, check the merchant dashboard
before creating a replacement; the original remains pending rather than charging again.

## Build and install

From `android-client`, with JDK 17 and Android SDK 36:

```powershell
.\gradlew.bat :pos:testDebugUnitTest :pos:lintDebug :pos:assembleDebug
```

Install `pos/build/outputs/apk/debug/pos-debug.apk` on the Android device.
The Android preview GitHub Actions workflow also produces the separate
`CL-Paints-POS-Android-preview` artifact after these changes are pushed.
This is an unsigned-for-production preview, not a Play Store submission.

Before live use, test on a physical Android device with the Solo Lite: staff
login/expiry, searches, cash totals, consent links, card approval/decline/cancel,
missing SumUp app, double taps, loss of connectivity, app termination during payment,
return callbacks and successful verification. Use SumUp's supported sandbox setup
first. No live device payment has been established by adding this code.

Server regression tests: `python -m unittest test_pos -q`.

References:
- https://developer.sumup.com/terminal-payments/readers/solo-lite/
- https://developer.sumup.com/terminal-payments/payment-switch/android/
- https://developer.sumup.com/api/transactions/get/
