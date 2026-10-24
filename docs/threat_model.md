# Threat model

Method: STRIDE over the components in [architecture.md](architecture.md), then the four adversaries the design was built around. Every control named here exists in the code and is exercised by a test; the attacks listed are run by `scripts/attack_suite.py` (results in [attack_suite.md](attack_suite.md)).

## Assets

Prescription contents (patient health information), the doctors' signing keys, the master key and audit keys, the integrity of the audit log, and the one-time nature of a prescription.

## STRIDE

| Threat | Example | Mitigation |
|---|---|---|
| **S**poofing | A fake doctor; a fake pharmacist | Doctors exist only if an admin creates them and they activate with a one-time token; each has their own ECDSA key. Pharmacists need admin approval. argon2id passwords, JWT revoked through `token_version`, lockout plus per-IP and per-account rate limits. |
| **T**ampering | Edit a dose on a PDF or photo; edit a database row | The signed payload is the only truth (what you see is what was signed). Uploads are compared field by field with a redrawn copy, plus OCR and the PDF text layer. Stored payloads are AES-GCM encrypted and hash-checked; plain columns are cross-checked against the signed payload. |
| **R**epudiation | A doctor denies issuing; a pharmacist denies dispensing | Digital signature; `dispenses` table; HMAC-chained audit log with signed checkpoints and an external anchor. |
| **I**nformation disclosure | Stolen database or storage folder; over-broad lookups | Envelope encryption of payload and PDF; private keys protected by the doctor's password; pharmacists see a masked patient name and nothing unless the signature verified; exact-match patient lookup. |
| **D**enial of service | Flood the verify endpoint; lock out a victim | Sliding-window rate limits by IP, account and user; 5 MB / 40 MP / 3-page upload limits; at most two image checks at once (503 when busy). Lockouts last minutes, not forever. |
| **E**levation of privilege | A pharmacist calls doctor endpoints; admin reads the audit log | `require_role` on every route, object-level checks that answer 404, a role-by-endpoint test matrix that fails if a route is unclassified, and a separate auditor role. |
| Replay | The same prescription at many pharmacies | Atomic dispense, `UNIQUE(rx_id, fill_no)`, expiry in the signed payload, cross-pharmacy alerts. |
| Stolen or photographed prescription | Someone else redeems it | The patient's PIN; the QR alone is not enough. |
| Insider abuse | A database administrator edits records or logs | Encrypted and signed payloads; a hash chain keyed with a secret the database does not hold; signed checkpoints; anchors outside the database. |

## The four adversaries

1. **The forger** has paper or a PDF and an image editor. They can change what is printed, but not the signature or the stored record. Render-and-diff, the text-layer check and the QR/hash checks catch the edit and name the field.
2. **The abuser** is an authorised user acting badly (a pharmacist replaying a prescription, a doctor writing absurd doses). The atomic dispense, the PIN, rate limits, the risk score, the alert rules and the audit log make it difficult and visible.
3. **The authenticated-abnormal user** behaves strangely with valid credentials (stolen doctor account). The anomaly model compares a prescription with that doctor's own habits; high-risk issuing needs a typed reason and raises an alert. This is a safety net, not proof; see the evaluation for its measured limits.
4. **The insider** can edit the database and files. They cannot forge signatures (no private keys without passwords), cannot decrypt prescriptions (master key is outside the database), and cannot edit the log without detection (HMAC key, signed checkpoints, external anchor). Truncating the newest entries is caught by the checkpoints and anchors.

## Out of scope (stated honestly)

- No hardware security module and no TLS in the local demo; run behind HTTPS and set `COOKIE_SECURE=true` for anything real.
- **Custodial signing:** the server decrypts a doctor's key in memory while signing. A fully compromised server plus a phished signing password could forge signatures.
- A fully compromised server that holds the master key and audit key defeats encryption and the log's secrecy assumptions.
- SQLite is single-writer and not production-grade; rate-limit counters live in one process.
- A pharmacist can still choose to hand over medicine against a forged page; the system gives them a refusal to rely on (and blocks that pharmacist from dispensing after a mismatching upload) but cannot physically stop it.
- Regulatory references (Schedule H/H1/X, DPDP Act, e-signature law) are illustrative, not legal advice.
- Photographed verification is only as good as the photo; poor photos give `REVIEW_REQUIRED`, never an accusation. The evaluation uses simulated photos.

## Residual risks we chose to accept

| Risk | Why accepted |
|---|---|
| The audit signing key also signs the anomaly model | One key to protect instead of two for a course demo; separating them is a small change. |
| Anomaly model is trained on synthetic data | No real prescribing data exists for the project; the report says what the numbers do and do not mean. |
| In-memory rate limiter | Correct for one process; documented for multi-worker deployment. |
