# Forms and booking tools

Open **Admin → Form builder**. Start with a template or create a draft.

## Editing and preview

- **Details:** title, introduction and customer-facing rules or booking information.
- **Blocks:** add questions, images and read-only instructions. Select a block on the grid, in the list or in the preview to open its settings. Only one settings panel opens at a time.
- **Schedule:** opening and closing times in UK time. Publish the saved form first; its date window then opens and closes automatically.
- **Receipts:** thank-you text and acknowledgement email wording.
- **Booking tools:** visual package/extra cards, notice period, maximum responses and an optional waiting list.

Use the persistent **Save draft** and **Preview** buttons. The phone preview stacks blocks; the desktop preview follows the twelve-column grid. Preview answers are never submitted. Published forms must be unpublished or duplicated before editing.

**Undo / Redo** keeps the last fifty edits in the current tab, including removed blocks, layout changes, wording and package settings. On the editor background, Ctrl/Cmd+Z undoes and Ctrl/Cmd+Shift+Z redoes; text inputs retain their normal text-editing shortcuts.

**Autosave** saves a valid draft after a short pause and displays its last saved time in UK time. Incomplete or invalid fields and unfinished uploads pause autosave; keep the tab open until the status confirms saving. New forms become drafts when their first valid autosave succeeds. Autosave checks for changes made in another tab and refuses to overwrite a newer version.

**Check before publishing** lists corrections and suggestions for the current draft. Save first to run server checks for uploaded images and all field definitions. Publishing also runs those checks on the server and blocks invalid forms or closing dates that have already passed.

## Booking features

| Feature | Where and how to use it |
| --- | --- |
| Availability checking | Customers enter event details and choose **Check dates and times**. Checks cover accepted bookings, manually blocked time and configured setup/travel buffers. Availability is advisory until you accept the request. |
| Packages | In Booking tools, add cards with a name, fixed event price, duration, description and optional uploaded image. Customers can choose a package or normal hourly pricing. Each event must meet the package duration and the site's minimum hours. |
| Extras and price estimates | Add priced extra cards in Booking tools. Extras are charged once per request. Package prices apply per event. The server checks selections and calculates the saved total; posted estimates are not trusted. Packages and priced extras use Client pays, without pitch fees. |
| Travel estimate | Customers can supply known one-way miles. The provisional estimate uses the configured included miles, rate and cap. CL Paints confirms the actual route and final charge; the estimate is not automatically added to the booking price. |
| Address lookup | The existing Google address suggestions require `GOOGLE_MAPS_API_KEY`. Manual address entry remains available. |
| Deposits and online payments | Accept the booking and set its deposit plan in Payments. With SumUp configured, customers can pay the remaining deposit or balance on a SumUp-hosted page. Successful payments are verified by the server and recorded once. Existing attached invoice links and manual cash/payment records remain available. |
| Booking amendments | Signed-in customers use the change/cancellation request controls in My bookings. Requests need administrator review; they do not silently change a confirmed booking. |
| Reminders | The existing `flask --app app send-booking-reminders --send` command sends due event reminders, balance details and setup prompts. Configure the public HTTPS URL, mail service and reminder notice period in Settings. Your host or Windows Task Scheduler must run the command regularly; opening the app does not install a scheduled job. Run without `--send` to preview the due list. |
| Calendar invitations | Accepted bookings include calendar downloads in My bookings. Customers download again after arrangements change. |
| Submission checklist | **Your forms → Insights & waiting list** shows seasonal requests needing review, deposit payments, contact/venue information or answer review. Bookings also retains its payment and status filters; customers have their own booking checklist. Participant waivers remain separate from private booking consent. |
| Form analytics | Insights shows sessions viewed, started and submitted, plus interaction counts grouped by question wording. No answer text is collected for analytics. These are approximate session counts, rather than unique people or a complete record of abandonment. |
| Booking cutoff | Set minimum notice in days in Booking tools. Every requested event date is checked on the server using UK dates. |
| Waiting list | Enable it and optionally set a maximum response count. Full forms direct visitors to the waiting list; the same link works for published forms outside their date window. Customers can also join when their preferred date is unavailable. Review entries and mark them Waiting, Contacted or Closed in Insights. Joining does not reserve a place or automatically send an invitation. |
| Group participants | Insert the ready-made Group participants repeating section from Blocks. One organiser can add names, ages and requirements; use separate participant permission questions when needed. Repeating sections support up to twenty rows and six fields per row. |
| Duplicate detection | Requests for the same customer email and event date are flagged against active requests in the admin booking view and seasonal checklist. They remain reviewable because a customer may arrange several legitimate events on one date. |
| Prefilled details | Signed-in customers use their saved contact/billing details. Consent confirmations must still be completed. |
| Review before submitting | Booking requests and native forms show a summary before their final submission. Hidden conditional questions are omitted. |
| Reference photos and captions | Insert the ready-made reference-photo section. Seasonal bookings also have design uploads and caption notes. Captions are matched to photos by filename or position. Files remain private. |
| Venue checklist | Insert the ready-made checklist and adapt shelter, table/chair, lighting and water-access questions to the event. |
| Submission PDFs | Signed-in owners can download their booking or native response. PDFs contain a text receipt, answers and recorded acceptance details. Drawn signatures remain in the original response; PDFs identify the signer rather than reproducing the drawing. The standard PDF font supports Western European text; other characters may be replaced. |
| Reusable blocks | Save the selected block or all blocks as a named group. Load, insert or delete saved groups from Blocks. Insertion gives colliding labels unique names and adjusts placement. Save the whole group when conditions or calculations depend on other blocks. |
| Scheduled opening/closing | Set opening/closing dates, save and publish. Forms accept responses only within their window, without needing a background job. |
| Spam protection | A hidden trap field and a persistent thirty-request-per-hour IP limit protect booking, native and waiting-list submissions. Login and form CSRF protections remain enabled. |

## SumUp setup

Set `SUMUP_API_KEY` and `SUMUP_MERCHANT_CODE` in the server environment, and configure an HTTPS **Public app URL** in Settings. Keep the API key on the server. SumUp credentials must be permitted to create and read checkouts. Hosted checkout support may depend on your SumUp merchant account.

The app uses [SumUp Hosted Checkout](https://developer.sumup.com/online-payments/checkouts/hosted-checkout) and verifies the checkout through [SumUp's checkout API](https://developer.sumup.com/api/checkouts/get). Callbacks are verified against the stored checkout ID, reference, merchant, amount and GBP currency. If a callback is delayed, use **Check payment status**. Unresolved checkout creation is kept for reconciliation rather than silently creating another charge attempt.

No live payment or email is sent by the automated tests. Live payment processing, API access, delivery and a deployed reminder schedule need to be verified in your hosting environment.

## Saved progress

Signed-in customers can recover their drafts across devices; guest seasonal drafts belong to the browser session. Packages, extras and caption notes are saved with seasonal drafts. File uploads, signatures and consent must be completed again. Draft recovery stops when the form changes so answers cannot silently be applied to a different version.

New supporting database tables are created by the existing startup setup. Existing booking and submission records are preserved.
