# Source: Razorpay — Payment Error Reasons & Downtime

- authority: Razorpay
- tier: authoritative
- urls:
  - https://razorpay.com/docs/errors/
  - https://razorpay.com/docs/payments/payments/payment-methods/downtime/
  - https://razorpay.com/docs/payments/tokenisation/
- retrieved: 2026-09-04
- note: Operator-maintained extract of documented error reasons and their handling guidance.

## Transient / infrastructure

- `gateway_technical_error`, `server_error`: an upstream error interrupted processing before
  authorisation. Safe to retry after a short backoff once de-duplicated against the original
  payment id.
- `payment_timed_out`: an upstream leg exceeded its timeout before authorisation was confirmed.
  Infrastructure latency, not a customer problem. Retry after a short off-peak backoff; a fresh
  1-click link is a reasonable parallel path if the customer is still on-session.
- Issuer / bank downtime is published on the downtime feed; when a bank is on that list, prefer
  nudging the customer to another rail rather than waiting on a retry.

## Authentication

- `incorrect_otp`, `3ds_authentication_failed`: the customer failed the OTP / 3DS step. The
  instrument is valid; recovery needs the customer present — send a 1-click link, or nudge UPI
  (which skips card OTP).
- `payment_canceled` / `payment_cancelled_by_user`: customer dismissed the authentication page.
  Often hesitation rather than a decision not to buy; one prompt re-attempt is reasonable.

## Method restrictions

- `card_disabled` / usage not enabled, `international_transaction_not_allowed`: the card cannot be
  used on this channel until the customer changes an issuer-app setting. Route to an enabled rail.
- `payment_limit_exceeded`: amount is above a per-transaction limit on the instrument. Switch
  method or split; do not retry the same amount.

## Hard declines

- `card_expired`, `lost_card`, `stolen_card`, `pickup_card`, `account_closed`: the instrument is
  permanently unusable. Zero retries; prompt the customer to use a different method once.

## Card-on-file tokens

- A charge against a token that has expired, been invalidated after card reissue, or was never
  created will fail. There is nothing to retry — re-collect the card with consent.
