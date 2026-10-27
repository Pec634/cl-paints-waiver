# Set up SumUp online payments

The portal is the CL Paints website where you manage bookings and clients, and
where clients sign in to view their bookings. Its existing SumUp integration
supports client-authorised GBP deposit and outstanding-balance payments using
SumUp Hosted Checkout. It does not charge cards automatically.

## 1. Prepare a test account

Sign in to your existing SumUp account. Open Developer Settings and create a
sandbox merchant in the Sandboxes section. Select that sandbox before creating
test credentials. Sandbox transactions do not move real money.

Official instructions: https://developer.sumup.com/online-payments/testing

## 2. Create credentials

In the SumUp Dashboard, open your profile, then Settings → For Developers →
Toolkit → API Keys. Create a secret API key named for this portal. The public
key displayed by SumUp is not the credential this integration needs.

Use the merchant code belonging to the same account as the key. If it is not
visible in the Dashboard, the authenticated `GET /v0.1/me` API response can be
used to inspect the merchant profile. Do not paste the secret key into chat,
browser code, or source control.

Official instructions: https://developer.sumup.com/tools/authorization/api-keys

## 3. Configure the server

Set these environment variables in the service hosting the portal:

```dotenv
SUMUP_API_KEY=your_secret_api_key
SUMUP_MERCHANT_CODE=your_matching_merchant_code
```

For local development only, these can go in the project's ignored `.env` file.
For a hosted service, use that service's private environment settings. Restart
or redeploy the app after setting them. Changing your computer's `.env` does
not configure a separate hosted service.

In the portal's notification/reminder configuration, set the public app URL to
the actual HTTPS address where clients access the portal. The app reads the
saved `public_app_url` setting; this is not a third environment variable.
SumUp must be able to reach that address for payment callbacks. A localhost
address alone is insufficient; use an HTTPS test deployment or a development
tunnel for end-to-end sandbox testing.

The app includes a per-checkout backend callback URL in each creation request.
It retrieves the checkout from SumUp before accepting a payment as successful.
Opening an invoice or returning to the portal does not itself confirm payment.

## 4. Test the payment journey

1. Review a test booking and finalise its price and travel charge. Set its deposit
   arrangement on the booking's Payments page, then use Bookings > Manage request >
   Reviewed - request payment. The booking now shows Awaiting Payment. New requests
   Under Review cannot start an online checkout.
2. Sign in as that booking's client and open the booking.
3. Under Online payments, choose Pay remaining deposit or Pay outstanding balance.
4. Complete payment on SumUp using a sandbox test card from the official testing
   guide. Test successful, declined, and 3D Secure challenge scenarios.
5. Confirm the verified payment appears once in the booking ledger and the
   outstanding balance updates. Repeating a callback must not duplicate it.
6. Once the deposit is recorded (or the full total if no deposit is set), use
   Confirm booking after payment. Payment alone does not confirm or complete the
   event. Confirmed bookings can still pay their remaining balance; completed,
   declined and cancelled bookings cannot start a new payment.
7. If the callback has not arrived, use Check payment status. If a checkout
   creation timed out, reconcile its status before attempting another payment.

Hosted Checkout sessions currently last 30 minutes. An old saved payment URL
may therefore expire. Before launch, include expiration and retry behaviour in
the end-to-end checks.

Official Hosted Checkout guide:
https://developer.sumup.com/online-payments/checkouts/hosted-checkout

Automated tests mock SumUp responses; they do not establish that the merchant
account or live payment processing is enabled:

```powershell
.\.venv\Scripts\python.exe -m unittest test_sumup_checkout
```

## 5. Enable real payments

After sandbox testing, replace both credentials with the live merchant's key
and matching merchant code on the production server. Confirm any account
requirements with SumUp, restart the app, and perform an explicitly authorised
small live payment before inviting clients to pay.

Invoice attachments and manually attached SumUp invoice links remain separate
from API checkouts. Their payment status is not automatically imported by this
integration. Refunds and saved-card charges are not implemented here.
