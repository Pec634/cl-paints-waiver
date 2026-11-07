# CL Creates messages, reminders and retention

Customers do not need accounts. Orders store the customer email, order number,
balance and a private payment token.

In **CL Creates → Shop setup → Pricing & showcase**, configure:

- Reminder days after order placement, such as `2,7,14`; blank disables reminders.
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
database. No external scheduler is provisioned by this change. The admin run button
works without a scheduler. Configure the HTTPS public app URL in business settings.

Before reminding an order with a started online checkout, the worker verifies it
with SumUp. Verification errors skip the order and are logged; paid orders are
never chased. Orders abandoned before starting checkout can receive their private
payment link. Legacy invoices cannot be automatically reconciled and do not receive
reminders. After downtime only the latest due reminder is sent. Sent stages are
recorded per order, failed stages can retry, and a 15-minute processing claim prevents
normal overlapping runs. A pending send after a process crash is retained for manual
investigation rather than risking a duplicate. As with other email jobs, database
records cannot guarantee exactly-once delivery by an external email provider.

Retention applies only to orders under review or awaiting payment with no received
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
