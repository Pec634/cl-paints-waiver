# CL Paints staff POS for Android

The `pos` module builds a separate **CL Paints POS** app for Android 8 or newer.
It opens the authenticated staff till at `https://my.clpaints.com/admin/pos`.
Deploy the server changes and restart it before using the app; startup creates
the `pos_sale`, `pos_product` and `pos_refund` tables and upgrades existing till
records. The existing client app remains a separate application.

## Included

- Named cashier and manager sign-ins, with the existing portal administrator kept
  as a management route. Staff enter only their allocated PIN, not a username or password. Cashiers sell library items; managers can override prices,
  manage items, refund payments and close day-end reconciliations. Each new sale
  retains the staff name and any custom-item or price-override flag.
- Search existing waivers by adult name, participant name, email or waiver reference.
  Results show participants, event, expiry and status. Archived waivers are excluded;
  expired or otherwise invalid waivers cannot be linked to a sale. Linking consent
  does not record attendance, award points, or extend consent.
- A shared item library with saved GBP unit prices, search and tap-to-add tiles.
  Use **Manage items & saved prices** to add, rename, reprice or remove items.
- Repeated taps increase basket quantities. Basket quantities and unit prices can
  be edited for individual sales, and lines can be removed. Custom items remain
  available. Library changes do not alter existing baskets or completed sales.
- On phones and smaller tablets, the till uses full-width Items, Waivers, History
  and Basket views with fixed bottom navigation, basket count and total. Linking
  a waiver returns to Items; searches, the basket and checkout identity survive
  switching views. Larger screens retain the side-by-side workspace.
- Basket lines have plus/minus quantity controls and item tiles show the quantity
  already added. Event, loyalty and email receipt options expand in the basket;
  their summary shows the current selection. Cash shortcuts set the tender to
  the exact total, GBP10, GBP20 or GBP50 and calculate change without completing
  the sale. Staff and day-end links are in the till header's Tools menu.
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
- Direct Solo Lite reader payments inside the Android POS, persistent pending sales
  and server verification. The separate SumUp app is not required by this APK.

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

## Staff and day-end setup

Restart the server after deploying these changes to create the staff, held-basket
and reconciliation tables and upgrade existing sale/refund/product columns. No
default staff PINs are created. Sign in as the portal administrator and open
**Staff accounts & permissions** in the admin menu (also under Tools > Staff
in the till). Create a named account, allocate its unique PIN and tick its allowed
portal areas. Existing accounts are expandable for editing. An enabled account
with no selected areas can sign in but cannot open portal tools. Till management
also grants point of sale; other areas are independent. Client profiles include
linked client history, as stated beside that permission. Owner settings, backups,
staff management and cross-portal search remain administrator-only.

Staff use `/admin/staff/login` or the existing `/admin/pos/staff/login`. Their
workspace, sidebar and phone menu show only their assigned areas. Till-only
cashiers still land directly in the till. Server checks protect GET, POST, JSON
requests and private attachments; permission edits and disabled accounts take
effect on the next request. Existing cashier/manager accounts retain only their
previous till permissions until edited. PINs still have no minimum length, are
hashed and unique, and repeated failures are throttled. Staff expire after 30
minutes idle or eight hours signed in. No administrator session is granted by a
staff PIN. The Android app's Admin tab opens their permitted workspace.

Use **Hold / resume baskets** to save a named basket while serving another customer.
Items, waiver selection, receipt preference and selected events are retained in
the database under the current sign-in. Hold or clear the current basket before
resuming another. A resumed basket keeps its sale token, including after a page
refresh, so repeating checkout returns the same saved sale. Previously resumed,
unsold baskets remain recoverable from the list.

Managers can set a category and **Quick item** flag in item management. Library
search, category and **Quick items only** work together to narrow the item tiles.

Open **Day-end** to compare the POS ledger with the physical cash count and the
SumUp net card total entered from the merchant report. Compare the same UK date,
before processing fees. Include non-sales cash added, removed and banked. Cash
and card differences are calculated live; closing requires checked counts and an
explanation for differences. Every save creates a retained revision. Later till
transactions invalidate the earlier reconciliation until a new revision is saved.
Daily handovers with till activity require a current closed reconciliation.

Refunds offer their own optional email receipt, using the original address when
available. Sending is logged and failed receipt emails can be retried without
repeating the refund. Refunds against a POS loyalty award are flagged **Needs
review** in the sale and manager queue. A manager records the review outcome;
actual point corrections remain in the portal administrator's event loyalty
ledger so other visits and free-paint cycles stay consistent.

See [tablet acceptance checks](TABLET-TESTING.md) for the physical device flow.

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

Install the updated POS APK over the existing preview. Start a card sale, tap
**Prepare SumUp payment**, then **Activate card reader and take ...**. On first
use the embedded SumUp SDK asks you to sign in; use the intended CL Paints
merchant's account. Allow the SDK's Bluetooth / nearby-device and location
permissions when requested, turn on Bluetooth and select the Solo Lite. The
app checks the SDK merchant code and GBP currency against the server before
starting checkout. A mismatched account is blocked before charging; use
**More > Sign out of SumUp**, then activate the reader and sign in again.

Payments now use the native SumUp reader SDK 7.1.0, which supports Solo Lite
and the existing Android Gradle Plugin 8 toolchain. SDK 7.2 requires an AGP 9
toolchain upgrade. SumUp's own payment UI appears within the POS application;
there is no switch to the separate SumUp app. Reader connection, battery,
firmware updates and pairing are available under **More > SumUp card reader**
after sign-in. Native merchant login uses the account's default merchant; use a
managed user for the intended merchant if the account has multiple merchants.
The SDK handles login credentials, not the portal. No API secret is in the APK.

The HTTPS preparation page still provides the legacy Payment Switch URI for
older APKs. The updated APK intercepts that URI only after a user tap on a
trusted prepared-sale page, validates it, and invokes native checkout instead.
Deploy the server update before using the new APK: the payment request now
includes the intended merchant code. The server environment variable names
and preview application ID are unchanged.

After checkout tap **Check payment with SumUp**. An SDK result or callback alone
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
first-use SumUp sign-in, wrong merchant, denied Bluetooth/location permissions,
double taps, loss of connectivity, app termination during payment, return
callbacks and successful verification. Use SumUp's supported sandbox setup
first. No live device payment has been established by adding this code.

Server regression tests: `python -m unittest test_pos -q`.

References:
- https://developer.sumup.com/terminal-payments/readers/solo-lite/
- https://developer.sumup.com/terminal-payments/sdks/android/
- https://developer.sumup.com/api/transactions/get/
