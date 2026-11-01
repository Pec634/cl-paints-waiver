# Moodboard payments

Customers scan the existing event moodboard QR, choose quantities of Small and Large designs, review their basket, and pay through one SumUp Hosted Checkout. Labels and prices are saved with the order so later moodboard edits do not change the purchased items. Waivers and loyalty remain separate.

Tap an image or its plus button to add one paint. The minus button removes one. Selected images have a highlight and quantity badge. The basket stays visible while scrolling. View larger opens a separate preview without changing quantities. The basket is remembered for the event in the current browser tab while customers review and edit it, then cleared when a paid confirmation is opened.

Review is server-priced and signed for 30 minutes. Changed prices or designs require a fresh review before creating a checkout. No SumUp checkout is created by the review step.

## Setup

- Configure `SUMUP_API_KEY` and `SUMUP_MERCHANT_CODE` on the server, using the intended SumUp merchant.
- Set the public app URL in business settings to the publicly accessible HTTPS application address. SumUp callbacks must reach this address.
- Set Small and Large prices in Moodboard Library and save the event's design selection.
- Open the event to enable checkout. Closed and archived events cannot create new orders.

The new order table is created through the application's existing `db.create_all()` startup process. Existing moodboard order tables receive fulfilment columns at startup, preserving orders. No existing booking payment tables change.

## Staff use

Open Events → Manage Moodboard → Moodboard payments to see event orders, their saved design labels, quantities, totals and payment status. Open an order to refresh its status directly from SumUp. Only provider-verified payments display Paid. The order list shows the last verified state; opening a confirmation refreshes unconfirmed payments.

Use Pause new orders when the queue is full, and Resume new orders to accept baskets again. Pausing keeps the gallery visible and blocks both new basket reviews and final checkout submissions, including reviews already open in another tab. Existing payment callbacks continue to be verified.

Paid orders start as Waiting. Staff select Start painting, then Mark all paints completed after the whole family's order is fulfilled. Completed orders cannot be started again. Status updates reject stale submissions from another staff tab. Customers can refresh their confirmation to see the current state; staff should check the order reference in the event list rather than rely on a screenshot.

Unconfirmed checkout creation is retained rather than retried automatically. Refresh the order status and check SumUp before creating another order. An expired or failed checkout requires a new basket. Previously issued payment links can remain payable until SumUp expires them even if the event is subsequently closed.

Payments are stored against the event in moodboard orders; they are not posted to booking invoices or awarded loyalty points. Refunds are handled through SumUp. Customers can revisit their private confirmation link without signing in.

## Validation before live use

Run `python -m unittest test_moodboard_payments test_moodboard_browser test_event_moodboard test_sumup_checkout test_event_deletion test_loyalty`.
Using sandbox credentials, verify a mixed basket, successful payment, failed payment, expired checkout, callback delivery and staff confirmation. No live payment was initiated during implementation.

For a manual UI check:

1. Open an event, save both Small and Large designs, then open its public moodboard.
2. Tap an image twice; verify its badge, quantity and total. Use minus to remove one.
3. Open View larger; verify the quantity stays unchanged and Close returns to the image controls.
4. Scroll on a phone-sized screen; the basket should stay visible without horizontal overflow.
5. Review a mixed basket, then choose Edit basket; quantities should be retained.
6. Pause orders from the staff screen; a stale review must be blocked from creating a checkout, while the moodboard stays visible.
7. Resume, complete a sandbox payment, and verify the order in the staff list.
8. Move it to Being painted and Completed; refreshing the customer confirmation should show the same state. A stale staff tab must not repeat a transition.

Provider reference: https://developer.sumup.com/online-payments/checkouts/hosted-checkout/
