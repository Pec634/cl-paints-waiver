# CL Creates messages, reminders and retention

Customers do not need accounts. Orders store the customer email, order number,
balance and a private payment token.

## Three-working-day payment deadline

Orders awaiting payment are automatically deleted after three Monday–Friday days, skipping weekends and preserving the UK placement time across daylight-saving changes. This also applies to existing unpaid orders awaiting payment. It is independent of the older archive/delete settings below. Received payments, part payments and attached invoices remain protected. SumUp payments are reconciled first, and an unpaid checkout must be deactivated and verified as expired before deletion. Provider errors preserve the order for retry.

After the first request, each serving process starts a background expiry check, initially after five seconds and then every five minutes. The database claim prevents overlapping workers from processing the same order. In-memory/test databases do not start this worker. A stopped or sleeping host cannot run checks; overdue orders are processed when the app resumes. The scheduled command below also applies this expiry policy and can be run by the deployment host when continuous processing is needed.

Customers see a cancellation/deletion notice before checkout and their exact UK-time deadline on the payment page. The page also has a copyable private link. They can bookmark it, save it and open it on another device without an account. The shop shows a return button for the latest order saved in the same browser session. Links stop accepting payment after the deadline; confirmed payments remain accessible.

The same five-minute worker sends one payment reminder at the placement time on the second working day. For example, a Friday order is reminded on Tuesday and expires on Wednesday. The email includes the amount, private payment link, exact UK-time deadline and a clear cancellation/permanent-deletion warning. This fixed reminder does not depend on the configurable legacy reminder days below. It requires automatic emails enabled, a configured email service and the HTTPS public app URL. Payments are checked first; part-paid orders and attached invoices are not chased. Failed sends retry the same message record; sent messages are not repeated. If the host resumes after the deletion deadline, the expired order is processed without sending a late reminder.

In **CL Creates → Shop setup → Pricing & showcase**, configure:

- Additional reminder days for older orders under review, such as `2,7,14`; blank disables these legacy reminders.
- Reminder subject and body using `{first_name}`, `{order_number}`, `{balance}`
  and `{payment_url}`. The existing automatic-email switch also controls reminders.
- Archive and permanent-deletion ages in days from order placement. Zero disables
  an action. Deletion must be later than archiving. Both default to disabled.

Save before using **Preview due actions** or **Process reminders and retention now**.
Preview does not contact SumUp or send email; its counts are estimates until
payment verification runs during application.

Schedule this command daily on the deployed host:

```sh
flask --app app process-creates-orders --apply
```

Omit `--apply` for a preview. The scheduler must use the same production database,
SumUp credentials and email credentials as the web app. A separate service cannot
use another service's local SQLite file; use the existing host scheduler or a shared
database. No external scheduler is provisioned by this change. The built-in worker handles the second-working-day reminder and three-working-day expiry. Legacy reminders and legacy retention still require this scheduled command or the admin run button. Configure the HTTPS public app URL in business settings.

Before reminding an order with a started online checkout, the worker verifies it
with SumUp. Verification errors skip the order and are logged; paid orders are
never chased. Orders abandoned before starting checkout can receive their private
payment link. Legacy invoices cannot be automatically reconciled and do not receive
reminders. After downtime only the latest due reminder is sent. Sent stages are
recorded per order, failed stages can retry, and a 15-minute processing claim prevents
normal overlapping runs. A pending send after a process crash is retained for manual
investigation rather than risking a duplicate. As with other email jobs, database
records cannot guarantee exactly-once delivery by an external email provider.

Legacy configurable retention applies only to orders under review with no received
money, started checkout, provider reference, payment URL or attached invoice. Paid
orders and unresolved payment records are protected. Protected orders are counted
in the run result; resolve them separately rather than deleting their payment history.
Archiving hides eligible orders from the default list and stops payment/reminders.
Search still includes archived history. Deletion removes the order and its messages
permanently. The worker logs archive/deletion order IDs; application backups follow
the host's separate backup policy.

New emails include an unguessable private message link. The page automatically
records **First viewed** when it becomes visible in the browser. A background tab
waits until selected. The browser sends a CSRF-protected POST; a plain GET does not
mark it viewed. The first timestamp is preserved on repeat visits. Failed requests
retry when the tab becomes visible again or the connection returns. Without
JavaScript, a manual confirmation button is available.

This tracks the linked message page, not opening the email itself. Anyone with the
link can trigger a view; it is not verified identity or proof of reading. JavaScript
capable scanners may also trigger it. Older emails cannot be tracked retrospectively.
Message pages are non-indexable and use no-store and no-referrer headers.

Validation:

```sh
python -m unittest test_creates_automation test_cl_creates test_creates_checkout
node test_creates_message_view.js
```
