# Source: RBI — e-mandates, Card-on-File Tokenisation, and Card Controls

- authority: RBI
- tier: authoritative
- urls:
  - https://www.rbi.org.in/Scripts/NotificationUser.aspx  (Processing of e-mandates on recurring transactions)
  - https://www.rbi.org.in/Scripts/BS_ViewMasDirections.aspx  (Tokenisation of Card Transactions)
- retrieved: 2026-09-04
- note: Operator-maintained plain-language extract. Verify against the current RBI notification /
  master direction before each release.

## e-mandate: pre-debit notification

- For recurring transactions processed on an e-mandate, the issuer / PSP must send the customer a
  pre-debit notification at least 24 hours before the actual debit.
- If that notification was not sent (or not acknowledged), the debit cannot be processed
  compliantly. The correct recovery is to send the notification now and schedule the debit at
  least 24 hours later — not an immediate retry.

## e-mandate: customer control

- A customer may pause / withdraw an e-mandate at any time. A paused or withdrawn mandate is not
  debitable and must not be auto-retried; collect the cycle out-of-band and invite the customer
  to resume.
- Each e-mandate carries a maximum amount. A debit above that amount is rejected.

## Card-on-File Tokenisation (CoFT)

- Since 1 October 2022, merchants and payment aggregators may not store actual card numbers.
  Recurring / 1-click card charges run against a network token.
- Creating a token requires the customer's explicit consent with an additional authentication
  factor. If tokenisation did not complete, there is no token to charge and the transaction fails.
- A stored token can become invalid when the card is reissued (new number / expiry), when the
  customer deletes it, or when the issuer invalidates it. Retrying an invalid token always fails;
  the customer must re-enter the card and re-consent.

## Card controls (on/off, limits)

- Cards are issued with online / e-commerce and international use switched off by default.
- The customer enables channels and sets per-transaction limits in the issuer's app.
- A transaction on a channel the customer has not enabled (or above a limit they have set) is
  declined until they change the setting; the effective recovery is to route to a rail that is
  enabled (UPI, netbanking, another card).
