# Cryptography specification

What Pramaan computes, with which algorithm and parameters, and why. Written from the code in `app/core/` (`canonical.py`, `crypto.py`, `keys.py`, `pin.py`, `qr.py`, `security.py`, `audit.py`) and `app/services/`. Every parameter below is exercised by a test in `tests/test_canonical.py`, `test_crypto.py`, `test_keys.py`, `test_pin.py`, `test_qr.py`, `test_audit_chain.py` and `test_security.py`. Only the `cryptography` library is used; nothing is home-made.

## Primitives at a glance

| Purpose | Algorithm | Parameters |
|---|---|---|
| Prescription signature | ECDSA over NIST P-256 with SHA-256 | Raw 64-byte `r‖s`; domain-separated (below) |
| Content hash | SHA-256 | Lowercase hex of the canonical bytes |
| Encryption at rest | AES-256-GCM | 12-byte random nonce per message, 16-byte tag, associated data (AAD) binds the context |
| Key wrapping (DEK, PIN secret) | AES-256-GCM under the master key (KEK) | AAD names the purpose, prescription and KEK version |
| Doctor private-key protection | PBKDF2-HMAC-SHA256, then AES-256-GCM | 600 000 iterations (floor 100 000), 16-byte salt |
| Patient dispense PIN | HMAC-SHA256 with RFC 4226 truncation | 6 digits, 120 s step, current and previous step accepted |
| Audit chain | HMAC-SHA256 | Keyed with `AUDIT_KEY`; links each entry to the one before |
| Audit checkpoints and model file | ECDSA P-256 / SHA-256 | Separate domain-separation strings |
| Login passwords | argon2id | `argon2-cffi` defaults, NFKC-normalised, 10 to 128 characters |
| Session token | JWT, HS256 | `sub`, `iat`, `exp`, `jti`, `tv`; algorithm allow-list |
| CSRF token | HMAC-SHA256 | Over the session's `jti` |
| Randomness | `os.urandom`, `secrets`, `uuid4` | Never `random` |

## 1. What is signed: canonical JSON

The doctor signs one exact byte string, so signer and verifier must derive identical bytes from the same prescription.

1. **Normalise every string to Unicode NFC**, so "é" typed as one character or as "e" plus an accent gives the same bytes.
2. **Reject** control, format, surrogate, private-use and unassigned characters (categories `Cc Cf Cs Co Cn`). That removes bidi overrides and zero-width characters, which can make text display differently from what was signed. A newline is allowed only inside `notes`.
3. **Reject floats** (their text form is not stable across platforms). Doses are whole milligrams.
4. **Reject duplicate keys** that collide after normalisation, so one of two values cannot silently win.
5. Serialise with **sorted keys, no whitespace** (`,` and `:` separators), `ensure_ascii=False`, `allow_nan=False`, UTF-8.

`payload_hash = SHA-256(canonical bytes)`, shown to people as a short fingerprint. The payload (version 2) holds: `version`, `rx_id`, `key_id`, `issued_at`, `expires_at` (UTC, seconds, `Z`), `max_fills`, the doctor block (`id`, `name`, `license_no`, `clinic`), the patient block (`id`, `name`, optional `age_years`), the medicines (`name`, `dose_mg`, `frequency`, `duration_days`) and `notes`.

Anything that cannot be printed faithfully (unsupported characters, text too wide for its box) is rejected **before** signing. The PDF is generated only from the payload, using the same text functions the content verifier uses; that is how "what you see is what you sign" holds by construction.

## 2. Signature

```
signature = ECDSA-P256-SHA256( key, "PRAMAAN-RX-v2\0" ‖ canonical_bytes )     (raw r‖s, 64 bytes)
```

- **Domain separation.** Three contexts exist: `PRAMAAN-RX-v2\0` (prescriptions), `PRAMAAN-AUDIT-v1\0` (audit checkpoints) and `PRAMAAN-MODEL-v1\0` (the anomaly model file). Each ends in a NUL byte, so no context is a prefix of another. A signature made for one purpose never validates for another, even with the same key.
- **Verification never raises on bad input.** A wrong length, a wrong key type or any decoding problem returns `False`.
- **Malleability.** An ECDSA signature `(r, s)` has a twin `(r, n−s)`. Both verify mathematically, but the verifier also compares the QR's signature bytes with the stored bytes in constant time, so a twin in a QR code is reported as an invalid signature.
- **Key identity.** `key_id` is the first 16 hex characters of SHA-256 over the public key's SubjectPublicKeyInfo DER. It is inside the signed payload and in the QR, and the verifier checks that both agree.

## 3. The QR code

```
PRM2.<rx_id>.<key_id>.<payload_hash>.<signature>
       uuid4  16 hex   64 hex          86 base64url characters
```

At most 300 characters. The parser is strict and runs **before** any database lookup: exact prefix, exactly five parts, each part matching a fixed pattern, and a base64url signature that must be the canonical encoding (non-zero trailing bits are refused) and decode to exactly 64 bytes. The code carries identifiers, the hash and the signature only, never the prescription, so a photographed QR reveals no medical details.

## 4. Doctor signing keys

- A P-256 keypair is generated when the doctor activates their account. The private key is serialised as PKCS#8 PEM and **encrypted** with AES-256-GCM under a key derived from the **signing password** by PBKDF2-HMAC-SHA256 (password NFKC-normalised, 16-byte random salt, 600 000 iterations by default; the application refuses fewer than 100 000).
- The AAD is `pramaan-doctor-key:<key_id>`, so an encrypted key cannot be moved to another doctor's record.
- A wrong password fails GCM authentication and never yields a wrong-but-valid key. After 5 failures in a row, signing is locked for 15 minutes, even for the right password.
- The signing password is separate from the login password (the server refuses equal ones), is never stored, and is never visible to an administrator. The unlocked key exists in memory only for the duration of one signing call.
- A doctor can rotate the key: the old key becomes RETIRED (it still verifies prescriptions already issued); suspending a doctor REVOKES every key and their unused prescriptions stop verifying.

## 5. Encryption at rest (envelope encryption)

Each prescription gets its own random 256-bit **data key (DEK)**. The DEK encrypts the payload and the PDF; the DEK itself is wrapped under the **master key (KEK)** from `MASTER_KEY`.

```
AAD = "pramaan:" ‖ purpose ‖ ":" ‖ rx_id [ ‖ ":" ‖ kek_version ]
purpose ∈ { payload, pdf, dek, redeem }
stored  = nonce(12) ‖ ciphertext ‖ tag(16)
```

Binding `rx_id` and the purpose into the AAD means a ciphertext cannot be swapped between prescriptions or reused for another purpose; binding `kek_version` stops a wrapped key being replayed under another key version.

**Master-key rotation** (`scripts/rotate_master_key.py`, `app/services/rotation.py`) unwraps each DEK and PIN secret with the old key and re-wraps it under the new one. Encrypted files are never rewritten. Before returning, the rotation proves that with the new key every payload decrypts and hashes to its recorded value and every PDF decrypts to its recorded hash; any failure rolls the whole transaction back.

## 6. Patient dispense PIN

```
secret  = random 256 bits per prescription (stored wrapped under the KEK)
PIN     = truncate6( HMAC-SHA256( secret, rx_id ‖ ":" ‖ counter_be64 ) )
counter = floor(unix_time / 120)
```

Truncation is RFC 4226 section 5.3 (checked against the RFC 6238 SHA-256 test vector). The server accepts the current and the previous time step, never the next, comparing both candidates every time so timing does not reveal which matched. Three wrong PINs for one prescription in five minutes lock dispensing for everyone, whoever the pharmacist is.

## 7. Audit log

```
entry_hash = HMAC-SHA256( AUDIT_KEY, prev_hash ‖ canonical({seq, ts, actor_id, actor_role, action, resource_id, details}) )
genesis prev_hash = 64 zeros
```

Someone with only the database cannot recompute a valid chain. Every 50 entries (and on demand) the head `seq:head_hash` is signed with the server's ECDSA audit key (context `PRAMAAN-AUDIT-v1\0`) and appended to an anchor file outside the database. `verify_chain` recomputes every hash, checks sequence and links, then compares the signed checkpoints and anchors with the database; it reports edits, recomputation attempts and tail truncation separately.

The log never holds passwords, keys, tokens, PINs, names or other personal data (keys such as `pin`, `name`, `email`, or anything containing `password`, `secret` or `private` are refused).

A single entry can also be checked on its own (`audit.entry_is_authentic`). Verification uses that for facts that are **not** in the signed payload but matter for safety: whether the prescription requires the patient's PIN is recorded in the sealed issue entry, and a prescription whose `require_pin` column no longer matches it is reported as tampered.

## 8. Login passwords, sessions and CSRF

- **Passwords:** argon2id with the library defaults, after NFKC normalisation; 10 to 128 characters (the upper bound limits the work per request). When an account does not exist, a dummy hash is verified so response time does not reveal which emails are registered.
- **Session token:** a JWT signed with HS256 using `SECRET_KEY`, carrying `sub`, `iat`, `exp` (30 minutes), a random `jti` and `tv` (the user's token version). Decoding passes `algorithms=["HS256"]` explicitly and requires all claims; expiry is checked against the application's own clock so tests can freeze time. The role is **not** in the token: it is read from the database on every request, and a version mismatch (logout, password change, deactivation) rejects the token at once.
- **Cookies:** the session cookie is `HttpOnly`, `SameSite=Strict`, and `Secure` when `COOKIE_SECURE=true`.
- **CSRF:** `HMAC-SHA256(SECRET_KEY, "pramaan-csrf:" ‖ jti)`, sent back by the page in `X-CSRF-Token` on every state-changing request made with a cookie. Because it is derived from the session's `jti`, it cannot be planted from another site and needs no server storage. Bearer-token callers (scripts) are not subject to it, since browsers do not attach those automatically. The same secret feeds the JWT and the CSRF tag; the fixed prefix keeps the two uses apart.
- **Activation tokens:** `secrets.token_urlsafe(24)` (192 bits), stored only as SHA-256, valid 24 hours, single use.

## 9. Randomness

Keys, nonces, salts, tokens and PIN secrets come from `os.urandom` or `secrets`; prescription ids are random UUIDv4. A fresh nonce is generated for every AES-GCM encryption, so a (key, nonce) pair is not reused.

## 10. Known limits

- **Custodial signing.** The server decrypts a doctor's key in memory while signing. A fully compromised server plus the doctor's signing password could forge signatures. The alternative (signing on the doctor's device) is listed as future work.
- **Python cannot reliably wipe memory.** Unlocked keys are dropped as soon as signing finishes, but are not zeroised.
- **Master key and audit key live in `.env` on the same host.** A host compromise exposes both. A production deployment would use a key-management service or HSM.
- **Mutable state is not signed.** Status, fills used and the PIN setting live in the database. Fills are protected by an atomic conditional update and `UNIQUE(rx_id, fill_no)`; the PIN setting by the sealed audit entry (section 7); the rest by the audit chain, which makes silent changes detectable rather than impossible.
- **Single process, SQLite.** Rate limits and lockout windows are per process.
