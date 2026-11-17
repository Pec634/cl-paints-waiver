# POS tablet acceptance checks

Automated checks cover desktop, phone and tablet viewports with simulated payment
and email responses. They do not establish that a physical card reader, merchant
account or email provider is configured correctly.

## Device setup

1. Deploy the server update and restart it before testing the installed POS app.
2. Install/open CL Paints POS and the SumUp app on the Android tablet. Sign into
   the intended merchant account and pair the Solo Lite in SumUp.
3. From the portal administrator sign-in, create one cashier and one manager via
   the till's **Staff** link. Sign in on the tablet with the cashier account.

## Checkout and recovery

1. Check both tablet orientations: the popup fits the screen, the basket is
   accessible, and waiver search updates without losing the current basket.
2. Find an individual waiver, link it and confirm its search folds away. Repeat
   with a collective waiver and choose the actual people being painted.
3. Use category filters and quick items. Add quantities and remove a line. Verify
   the cashier cannot change prices or issue refunds.
4. Hold a named basket. Serve a second basket, then resume the first and verify
   item quantities, waiver, receipt preference and event selection. Refresh once
   and confirm the basket still has the same checkout identity.
5. Complete a cash sale with more cash tendered than the total. Verify change,
   the saved sale time/staff name, and the optional receipt in the chosen inbox.

## Reader flow (performed by the merchant with an agreed test amount)

1. Create a card sale and start SumUp once. Complete the reader payment, return
   to CL Paints and check payment verification.
2. Verify the saved total, original SumUp reference, waiver link, receipt status
   and loyalty award. Refresh/check again and confirm no duplicate payment or point.
3. Check cancellation and interrupted-return recovery: the till must not mark
   an unverified payment paid or enable a second launch of the same payment.
4. Sign in as a manager. Refund selected remaining quantities, then the rest.
   Compare each refund against SumUp and verify the item/refund history and email.
   For an uncertain response use **Check refund with SumUp**, not a new refund.

## Day end

1. Compare the daily item summary with the saved sales and confirmed refunds.
2. Check each transaction is allocated to the intended event cash-up and not
   repeated in the additional manual takings fields.
3. Review any refunded loyalty awards. Record whether the point is retained or
   have the portal administrator make the audited correction in event loyalty.
4. Enter opening/non-sales cash, counted cash and the day's SumUp net card total
   before fees. Confirm live differences, save the reconciliation, and complete
   the handover. Print the saved report and verify the retained item snapshot.
5. Record the device model, Android/SumUp versions, merchant, transaction/refund
   references, results and any discrepancy in the merchant's test notes.

Physical testing was not run in the development session: no Android device was
connected. No live card payment, refund or customer email was initiated by the tests.
