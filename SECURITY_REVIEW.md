# Initial security review — 5 October 2026

This is a focused code review, not a penetration test or a security guarantee.

## Implemented in this change

- Admin password submissions require a session-bound CSRF token.
- Login allows five attempts per source address per 15 minutes, persisted in
  the database; subsequent attempts return 429. Proxy deployments may share a
  source address: check Render's proxy behaviour before relying on this as a
  complete per-client IP control. The app does not trust arbitrary forwarded IPs.
- Admin-protected requests expire the admin sign-in after 30 minutes without
  an admin action. Client session expiry is separate. This is checked on the
  next protected request, not by a background timer.
- Optional password + email-code sign-in: ADMIN_EMAIL_VERIFICATION=true.
  Configure the recovery email in Settings and working Resend credentials first.
  A code is hashed, expires after 10 minutes, allows five guesses and is consumed
  atomically. Email verification is weaker than authenticator/passkey MFA and
  depends on securing the email account. Delivery failure does not sign in.
- HttpOnly and SameSite=Lax session cookies; Secure on Render (RENDER=true).
  nosniff, SAMEORIGIN framing, referrer policy and no-store on private routes.
  SAMEORIGIN allows the existing kiosk/preview frames. HSTS is set on the
  production secure-cookie configuration.
- Local debug mode is opt-in through FLASK_DEBUG=1. Render should run Gunicorn,
  not the development server. Use a strong persistent SECRET_KEY on Render.

## Audit findings still requiring work

- Legacy admin mutation routes need comprehensive CSRF checks: moodboard
  upload/rename/delete, event creation/rename/status/delete, booking management
  and event generation, legacy referral mutations and waiver archive/delete.
  Authentication alone does not prevent CSRF. Audit every form and API action;
  do not treat the login CSRF fix as covering those routes.
- Review password-reset and public waiver submissions for durable rate limits
  and spam prevention; also review admin logout as a state-changing action.
- A single shared admin credential does not provide staff-level accountability.
  Add individual staff accounts/roles before exposing admin access to the team.
- Add an audit trail for changes to bookings, payments, loyalty and consent;
  exclude passwords, verification codes, tokens and complete sensitive form data.
- Automate separate protected backups and test restores. Establish data
  retention schedules and access/deletion procedures with the privacy review.
- Check upload limits, dependencies, secret rotation and deployment settings.
  CSP needs a tailored rollout because templates currently use inline scripts,
  Google address integration, hosted images and same-origin frames.

No Connecteam key has been changed. No email verification codes were sent during
tests. The initial safeguards do not resolve every item listed above.
