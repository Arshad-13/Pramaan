# Security review: crypto, authentication and dispensing

Done Tue 27 Oct 2026, the day of feature freeze, by reading the code line by line against the threat model. It complements the automated checks (bandit, the role-by-endpoint matrix, the attack suite) rather than replacing them.

**Read in full:** `app/core/{crypto,keys,canonical,pin,security,audit,qr,net,ratelimit}.py`, `app/deps.py`, `app/routers/{auth,verify,prescriptions}.py`, `app/services/{account,key,prescription,verification}_service.py` and `rotation.py`.
**Not reviewed in depth:** the image and OCR code in `app/ai/`, PDF rendering, and the frontend (covered by tests and the accessibility run, not by this review).

## What was checked and found sound

- **Signatures:** one fixed context string per purpose; verification returns `False` instead of raising; a twin `(r, n−s)` signature in a QR code is rejected by the byte comparison with the stored signature. Key id is signed and cross-checked.
- **Encryption:** a fresh random nonce for every AES-GCM call; AAD binds purpose, prescription id and key version, so ciphertexts cannot be swapped. A wrong password or altered ciphertext fails authentication.
- **Canonical form:** NFC, forbidden character classes, no floats, collision-checked keys. Nothing is truncated silently.
- **Passwords and sessions:** argon2id with a dummy hash for unknown accounts, generic 401 for unknown, locked and not-yet-activated accounts, explicit JWT algorithm allow-list, role read from the database on every request, `token_version` revocation, CSRF bound to the session id and compared in constant time.
- **Dispense:** the QR is fully re-evaluated inside the dispensing transaction; only `VALID` can be dispensed (suspicious, review-required and expired all refuse); the fill is consumed by one conditional `UPDATE` and backed by `UNIQUE(rx_id, fill_no)`. Every SQLite transaction begins with `BEGIN IMMEDIATE`, so concurrent PIN guesses are serialised and cannot slip past the three-try limit.
- **PIN:** constant-time comparison of both time steps, malformed PINs are simply wrong, the failure count is kept per prescription in the audit log.
- **Object-level access:** doctors and patients see only their own prescriptions and get 404 (not 403) otherwise; patient lookup is exact-match only.
- **Logging:** audit details refuse keys that look like secrets or personal data; the access log never records query strings or bodies.

## Findings

| # | Severity | Finding | Status |
|---|---|---|---|
| R1 | Medium | **The PIN requirement was not covered by any signature.** `require_pin` is a plain column on `prescriptions`, and the cross-check of database columns against the signed payload did not include it. Someone who could write to the database could set it to `0`, after which a pharmacist could dispense with only an "identity checked" tick-box and the patient's consent was bypassed. | **Fixed.** The setting is now recorded in the chained, HMAC-sealed issue entry of the audit log. Verification compares the column with that entry and reports `TAMPERED` (`DB_RECORD_ALTERED`) on a mismatch, or if the entry itself was edited. A database-only attacker does not hold the audit key, so they cannot reseal it. Prescriptions issued before this change have no recorded setting and keep working as before. Tests: `tests/test_security_review.py`. |
| R2 | Low | `GET /patients/lookup` had no rate limit, so a doctor account (or a stolen session) could script "is this email a patient here?" at full speed. | **Fixed.** Per-doctor limit of 30 a minute (the same budget as verification). |
| R3 | Low | Account lockout can be used against a victim: anyone who knows an email address can lock that account for 15 minutes with five wrong passwords, the administrator included. | **Accepted.** The lock is short, sign-in attempts are limited per address and per account, and a `FAILED_LOGINS` security event is raised. A permanent lock or CAPTCHA would be worse for the demo and the user. |
| R4 | Low | Three wrong PINs lock dispensing of that prescription for five minutes for every pharmacist, so a malicious pharmacist can delay a legitimate dispense. | **Accepted.** It is the price of an attacker not being able to guess a six-digit PIN; a `PIN_LOCKED` event is raised and the delay is five minutes. |
| R5 | Low | Registering with an email that exists answers 409 "already exists", which reveals that the address has an account. | **Accepted.** Common trade-off for self-service sign-up; registration is limited to 10 a minute per address. Sign-in itself does not leak this. |
| R6 | Info | The JWT secret also keys the CSRF HMAC. | **Accepted.** The CSRF input has a fixed prefix (`pramaan-csrf:`) and the JWT carries a different structure, so the two uses cannot be confused. |
| R7 | Info | Login also returns the token in the JSON body. | **Accepted**, documented in `assumptions.md`. |

## Result

One medium and one low finding fixed, five items accepted with reasons. No finding allowed a signature to be forged, a prescription to be dispensed twice, or a protected record to be read without authorisation. The full test suite, `bandit` and the attack suite (16 of 16) pass with the fixes in place.
