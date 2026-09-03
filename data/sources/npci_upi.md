# Source: NPCI — Unified Payments Interface (UPI)

- authority: NPCI
- tier: authoritative
- urls:
  - https://www.npci.org.in/what-we-do/upi/product-overview
  - https://www.npci.org.in/what-we-do/upi/circular
- retrieved: 2026-09-04
- note: Operator-maintained extract of publicly documented UPI rules. Figures must be
  re-verified against the latest NPCI circular before each release — limits are revised periodically.

## Transaction limits

- Standard per-transaction UPI limit is around ₹1,00,000 for most person-to-merchant use cases.
- Higher ceilings apply only to specific verified categories (e.g. capital markets, insurance,
  foreign inward remittance, some education and healthcare flows) — up to ₹2,00,000 or ₹5,00,000.
- Member banks and PSP apps may enforce their own lower per-transaction and per-day limits.
- A cumulative daily cap applies per user, by amount and by transaction count (banks/apps commonly
  cap the count in the 10–20 range per day).
- Retrying the same amount on the same rail after a limit rejection will fail again — the customer
  must split the amount or use another rail.

## New-user risk cooling period

- For roughly the first 24 hours after a customer registers a new UPI ID or links a new bank
  account, total UPI transfer value is capped (commonly ₹5,000) as a fraud-containment measure.
- This restriction clears automatically after the cooling window; it is not permanent and does
  not warrant human escalation.

## UPI PIN (MPIN)

- Entering an incorrect UPI PIN the maximum number of times (typically 3) triggers a temporary
  lock on UPI PIN usage for that account, often for about 24 hours.
- The bank account itself is unaffected. UPI on that handle cannot be used until the lock clears
  or the customer resets the UPI PIN.

## Collect requests

- UPI collect (pull) requests have a short approval window set by the PSP.
- If the payer does not approve within the window the request lapses with no debit.
- Collect has structurally lower completion than UPI intent / QR; prefer re-issuing as intent.

## UPI AutoPay (recurring mandates)

- UPI AutoPay mandates are created with a maximum per-transaction amount approved by the customer.
- A debit above that approved maximum is rejected by the payer bank.
- Execution without an additional authentication factor is allowed only up to the RBI-specified
  e-mandate ceiling; above that the customer must authenticate each debit.
- A mandate that is paused, revoked or not yet active cannot be debited and must not be retried
  as if it were a transient failure.

## PSP app availability

- A payer's UPI app / PSP (Google Pay, PhonePe, Paytm, BHIM, etc.) can be unavailable while the
  underlying bank and NPCI switch are healthy. This is distinct from issuer-bank downtime and is
  usually short-lived; a brief retry or a switch to another PSP app resolves it.
