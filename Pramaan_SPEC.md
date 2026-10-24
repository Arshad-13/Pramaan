# Pramaan: Tamper-Proof Prescription Verifier (Spec v2)

> *Pramaan (प्रमाण) means "proof" in Hindi: every prescription carries cryptographic proof of who issued it and that it was never altered.*

> **Course:** AI 331 Information Security and Cryptography, SVNIT Surat (B.Tech AI, Sem 5)
> **Domain:** Healthcare
> **Team size:** 3-4 | **Deliverables:** Code repository + presentation deck
> **Status of this file:** Single source of truth. Read it fully before writing any code.
> **Version:** v2 (revised after a full plan review). Phase-by-phase tracking is in `PHASE_CHECKLIST.md`.

---

## 0. Instructions for Claude Code (read first)

1. Read this entire file before creating anything. Do not start coding from the summary alone.
2. Build **phase by phase** (Section 15), as **vertical slices**: each phase from P4 onward ships a thin React page so the demo always works end to end. Finish a phase, run its tests, confirm its acceptance criteria, then move on.
3. Respect the **tiers** (Section 2). Never start a Tier 1 or Tier 2 item while a Tier 0 item is unfinished.
4. Keep the project **beginner-friendly**: plain Python, small modules, clear names, docstrings explaining *why* each security decision exists. Avoid clever abstractions.
5. Follow the folder layout in Section 5. If you must deviate, say why in a comment and update this file.
6. Never invent crypto. Use only the `cryptography` library primitives named in Section 7. Never implement your own cipher, hash, signature or MAC.
7. Never log, print, or store plaintext passwords, private keys, the master key, audit keys, PINs, or JWT secrets.
8. Every security-relevant action writes an audit entry (Section 9) **in the same database transaction** as the action itself.
9. All time comes from `app/core/clock.py` (`now_utc()`); never call `datetime.now()` elsewhere. Tests and the demo rely on this.
10. The app **refuses to start** with placeholder or malformed secrets (Section 8.5).
11. When a requirement is ambiguous, pick the simplest option that satisfies the acceptance criteria, then note the assumption in `docs/assumptions.md`.
12. Everything must run locally on a laptop (Windows 11 is the primary dev OS) with **no GPU, no paid services, and no downloads at runtime** (all models and data ship with the pip packages or the repo).
13. This is an academic demo. Medical reference values in `data/` are approximate and **not for clinical use**. Add that disclaimer to the README and the UI footer.

---

## 1. Project Summary

**One-liner:** A doctor issues a digitally signed prescription with a QR code. A pharmacist scans it and instantly learns whether it is **genuine, tampered, expired, already used, revoked, or suspicious**. The patient has to consent to dispensing. Every action is recorded in a tamper-evident log.

**Problem:** Forged, edited, stolen and reused prescriptions are a real problem (especially for controlled drugs). Paper and PDF prescriptions have no built-in integrity, authenticity or replay protection.

### 1.1 Layered defence: three adversaries, three layers

Pramaan is organised around *who* is attacking, not around technologies. This is the story for the deck.

| Adversary | Example | Layer that stops them | Evidence in the demo |
|---|---|---|---|
| **Outsider / forger** | Edits a dose on a PDF, forges a QR, photographs someone's prescription | **Cryptography**: ECDSA signatures, SHA-256, render-and-diff content check, patient-consent PIN | Edited image => TAMPERED with the altered cell outlined |
| **Abuser of the system** | Replays a QR at many pharmacies, brute-forces logins, floods the API, tries privilege escalation | **Information security**: RBAC, atomic one-time dispense, expiry, rate limits, lockout, alerts | Second pharmacy => ALREADY_USED + security alert |
| **Authenticated but abnormal** | Rogue prescriber or a stolen doctor account issuing absurd or out-of-pattern prescriptions | **AI**: drug validation, dose limits, interaction rules, per-doctor anomaly detection | Fake drug or absurd dose => SUSPICIOUS with explanations |
| **Insider with database access** | Edits records or the audit log, deletes log tail | **Cryptography + audit**: signed payloads, encrypted payloads, HMAC-chained log with signed checkpoints | Tamper script => chain verification fails at the right row |

### 1.2 What makes this project different (five differentiators)

1. **Render-and-diff tamper localisation (AI/CV).** The verifier re-renders the *expected* prescription from the signed payload using the same layout, aligns the uploaded image using fiducials, and compares it zone by zone. It does not rely on OCR reading every digit correctly, and it shows *exactly which cell was edited*. OCR is secondary evidence (Section 11.2).
2. **Patient-consented, one-time dispensing.** A stolen or photographed prescription is useless without a short-lived PIN shown only in the patient's app (HMAC/TOTP-style). Refills are supported for non-controlled drugs (Section 8.3).
3. **Audit log that survives an insider.** HMAC-keyed hash chain plus ECDSA-signed checkpoints anchored outside the database: detects edits, recomputation and truncation (Section 9).
4. **Honest trust model.** Admin never learns doctor passwords (activation flow), key lifecycle with rotation/revocation, WYSIWYS signing, and a documented list of what is *not* protected (Section 22).
5. **Automated attack suite.** `scripts/attack_suite.py` runs ~15 attacks against a live instance and prints "attack, control that caught it, result". It is both the demo and the evidence slide (Section 14.3).

### 1.3 Core design principle: WYSIWYS

**What You See Is What You Sign.** The PDF is rendered *only* from the signed payload. Every visible field (clinic, doctor, licence, patient name, dates, medicines, notes) exists in the payload, and every one is checked when a document is uploaded. The signed record, not the paper, is the authority; the pharmacist is always shown the verified record and told to dispense from it.

### 1.4 How the required domains are covered

| Domain | What we implement |
|---|---|
| **Cryptography** | ECDSA P-256 signatures with domain separation, SHA-256, AES-256-GCM envelope encryption (payload + PDF) with KEK rotation, PBKDF2 key protection, HMAC (audit chain, patient PIN), signed audit checkpoints, signed model file |
| **Information Security** | RBAC (5 roles) + object-level checks, argon2id, JWT with server-side revocation, activation tokens, pharmacist approval, atomic one-time dispense with DB uniqueness, expiry, revocation, rate limiting, lockouts, security alerts, STRIDE model, CI security scans |
| **Artificial Intelligence** | Render-and-diff computer vision, OCR (RapidOCR), fuzzy drug matching, dose and interaction rules, Isolation Forest + per-doctor behaviour features, explainable risk score, evaluated with ablation and model comparison |

---

## 2. Scope Tiers and the Cut Line

If time runs short, cut from the bottom. **Never cut Tier 0.**

| Tier | Items | Phases |
|---|---|---|
| **Tier 0: must ship** | Crypto core, audit log (HMAC chain + checkpoints), auth + RBAC + activation, issue + QR + PDF + encryption, QR verification, atomic dispense, expiry/revoke/replay, drug+dose rules risk score, React frontend pages for all roles (including the live QR scanner), README, tests, deck | P0-P6, P10-P11 |
| **Tier 1: should ship** | Upload verification with render-and-diff + OCR, Isolation Forest + evaluation, patient PIN, rate limiting + alerts + hardening, auditor role, KEK rotation, attack suite, CI scans, interaction rules | P7-P9 |
| **Tier 2: stretch** | Offline-verifiable QR (Section 22.2), live in-browser QR scanner, pediatric dose rules, Docker Compose, non-custodial signing prototype | P11 |

**Non-goals:** real hospital/pharmacy integration, payments, inventory, real regulatory compliance, mobile app.

**13-day window (deadline 31 Oct 2026):** Section 16 lists exactly which Tier 1 and Tier 2 items are cut or reduced. Where this table and Section 16 disagree, Section 16 wins.

---

## 3. Users and Roles

| Role | Can do | Cannot do |
|---|---|---|
| **doctor** | Activate account, issue prescriptions, view/revoke own, rotate own key | Verify/dispense, view audit log, see other doctors' prescriptions |
| **patient** | View/download own prescriptions, see the dispense PIN | Issue, verify, dispense |
| **pharmacist** | Verify prescriptions (QR or upload), dispense with patient PIN | Issue, revoke, view audit log. Account must be **approved** by an admin first |
| **admin** | Create doctor accounts (activation token), approve pharmacists, deactivate/suspend users, revoke a doctor key | Issue or dispense prescriptions, read or modify the audit log |
| **auditor** | Read audit log, run chain verification, create checkpoints, view security events | Anything that changes state except `AUDIT_VERIFIED`/checkpoint entries |

- Patients self-register. Pharmacists self-register with licence number + pharmacy name and stay `PENDING` until an admin approves.
- Doctors are created **only by an admin**, who supplies name, email and licence number (NMC/state-council style registration number). The admin receives a one-time **activation token** (shown once, stored as SHA-256, valid 24 h) and hands it to the doctor. The doctor sets their own login password and a *different* signing password; the keypair is generated at that moment. The admin never sees either password.
- If a team prefers three roles for the demo, `auditor` can be played by the admin account, but the code must still implement the separate role.

---

## 4. Tech Stack

| Layer | Choice | Notes |
|---|---|---|
| Language | **Python 3.11** | Create the venv with `py -3.11 -m venv .venv`. Not 3.14 (the default `python` on the dev machine): many ONNX/OpenCV wheels do not support it yet. 3.12 is listed by `py -0p` there but is not actually installed |
| Backend | FastAPI + Uvicorn | Pydantic v2 |
| DB | SQLite via SQLAlchemy 2.x | WAL mode, `busy_timeout`, `BEGIN IMMEDIATE` for writes (Section 9) |
| Crypto | `cryptography` | ECDSA, AES-GCM, PBKDF2, HMAC, SHA-256 |
| Passwords | `argon2-cffi` | argon2id |
| Auth tokens | `PyJWT` | HS256, always `algorithms=["HS256"]` on decode |
| Rate limiting | small in-memory sliding-window limiter (`core/ratelimit.py`) | per-IP and per-account keys that a decorator library cannot see (Section 8.4) |
| QR create | `qrcode[pil]` | error correction M |
| QR decode + CV | `opencv-python-headless` | prefer `cv2.QRCodeDetectorAruco` (OpenCV >= 4.8), fall back to `QRCodeDetector` |
| PDF create | `reportlab` | deterministic layout from `pdf_layout.py` |
| PDF read/render | `PyMuPDF` (`fitz`) | pip-only |
| OCR | `rapidocr-onnxruntime` (default) | ONNX models ship inside the wheel: no PyTorch, no runtime download. `easyocr` and `pytesseract` stay optional behind the same interface |
| Fuzzy matching | `rapidfuzz` | |
| ML | `scikit-learn`, `numpy`, `pandas`, `joblib`, `matplotlib` | Isolation Forest; matplotlib for evaluation figures |
| Frontend | **React 18 + TypeScript + Vite, Tailwind v4, shadcn/ui, Motion, TanStack Query** | Full details in Section 13.0. Needs Node 20.19+/22+ (Node 24 installed) |
| Tests | `pytest`, `pytest-cov`, `httpx`, `hypothesis` | |
| Quality / security tooling | `ruff`, `black`, `bandit`, `pip-audit` | run in CI |

**Reproducibility:** at the end of Phase 0, run `pip freeze` on a clean venv and commit pinned versions to `requirements.lock`. `requirements.txt` stays loose; `requirements-dev.txt` holds test and lint tools.

### `requirements.txt`

```
fastapi
uvicorn[standard]
sqlalchemy>=2.0
pydantic>=2.0
pydantic-settings
python-multipart
cryptography
argon2-cffi
PyJWT
qrcode[pil]
opencv-python-headless
reportlab
PyMuPDF
rapidocr-onnxruntime
rapidfuzz
scikit-learn
numpy
pandas
joblib
matplotlib
```

(The frontend's JavaScript dependencies live in `frontend/package.json`. Scripts and the attack suite use `httpx` from the dev requirements.)

### `requirements-dev.txt`

```
-r requirements.txt
pytest
pytest-cov
httpx
hypothesis
ruff
black
bandit
pip-audit
```

### `.env.example`

```
DATABASE_URL=sqlite:///./pramaan.db
SECRET_KEY=GENERATE_WITH_scripts/gen_keys.py     # JWT signing secret, >= 32 bytes
MASTER_KEY=BASE64_OF_32_RANDOM_BYTES             # KEK for envelope encryption
MASTER_KEY_VERSION=1
AUDIT_KEY=BASE64_OF_32_RANDOM_BYTES              # HMAC key for the audit chain (the patient PIN uses a per-prescription secret)
AUDIT_SIGNING_KEY_PATH=./secrets/audit_signing.pem   # ECDSA key for audit checkpoints and model signatures
ACCESS_TOKEN_MINUTES=30
PBKDF2_ITERATIONS=600000
STORAGE_DIR=./storage
ANCHOR_FILE=./storage/anchors.jsonl              # append-only checkpoint copy outside the DB
RISK_THRESHOLD=60                                # risk >= this => SUSPICIOUS
MAX_FAILED_LOGINS=5
LOCKOUT_MINUTES=15
MAX_FAILED_UNLOCKS=5                             # wrong signing password attempts
PIN_STEP_SECONDS=120
FROZEN_TIME=                                     # demo/testing only, ISO timestamp or empty
DEBUG=false
CORS_ORIGINS=http://localhost:5173               # dev only (Vite); production is same-origin
TRUSTED_PROXY_IPS=                               # empty = trust no forwarded-IP headers
COOKIE_SECURE=false                              # set true when served over TLS
```

`scripts/gen_keys.py` generates and prints fresh `SECRET_KEY`, `MASTER_KEY`, `AUDIT_KEY` values and creates the audit signing PEM. Nothing is ever committed.

---

## 5. Repository Layout

```
pramaan/
├── README.md
├── Pramaan_SPEC.md              # this file
├── CLAUDE.md                    # short pointer: "See Pramaan_SPEC.md"
├── requirements.txt / requirements-dev.txt / requirements.lock
├── .env.example
├── .gitignore                   # .env, secrets/, *.db, storage/, data/models/*.joblib, __pycache__
├── Makefile                     # dev, test, lint, seed, demo (thin wrappers)
├── .github/workflows/ci.yml     # ruff + black --check + bandit + pip-audit + pytest --cov
├── app/
│   ├── main.py                  # FastAPI app, routers, middleware, CORS, limiter, startup checks
│   ├── config.py                # pydantic-settings; validates secrets, fails closed
│   ├── db.py                    # engine (WAL, busy_timeout, BEGIN IMMEDIATE), SessionLocal, get_db
│   ├── models.py                # SQLAlchemy models
│   ├── schemas.py               # Pydantic request/response models
│   ├── deps.py                  # get_current_user (loads from DB), require_role()
│   ├── core/
│   │   ├── clock.py             # now_utc(), supports FROZEN_TIME
│   │   ├── canonical.py         # NFC normalisation, canonical JSON, SHA-256
│   │   ├── crypto.py            # sign/verify, AES-GCM, HMAC helpers, envelope encryption
│   │   ├── keys.py              # keypair generation, password-protected private key, key_id
│   │   ├── qr.py                # build/parse QR string, render PNG, decode from image
│   │   ├── pdf_layout.py        # SINGLE source of truth for zones, fiducials, fonts, positions
│   │   ├── pdf.py               # prescription PDF from payload only (reportlab)
│   │   ├── audit.py             # HMAC-chained audit log, checkpoints, verify
│   │   ├── pin.py               # patient dispense PIN (HMAC-based, TOTP-style)
│   │   ├── security.py          # argon2, JWT, lockout, token_version helpers
│   │   └── events.py            # security events + alert rules
│   ├── ai/
│   │   ├── ocr.py               # OCREngine protocol + RapidOCR impl (+ optional others)
│   │   ├── rectify.py           # fiducial/QR detection, homography to canonical page
│   │   ├── render_diff.py       # render expected page from payload, per-zone comparison
│   │   ├── extract.py           # regex extraction of drug/dose/frequency/duration
│   │   ├── drug_match.py        # exact+fuzzy match vs data/drugs.csv, dose checks
│   │   ├── interactions.py      # data/interactions.csv lookups (Tier 1)
│   │   ├── features.py          # feature building for anomaly model (shared by train + infer)
│   │   ├── anomaly.py           # Isolation Forest inference + explanations
│   │   ├── model_io.py          # sign/verify model artifacts before joblib.load
│   │   └── risk.py              # combine rules + anomaly into score, flags, explanations
│   ├── services/
│   │   ├── account_service.py       # activation, approval, suspension
│   │   ├── prescription_service.py  # issue, revoke, list, key rotation
│   │   └── verification_service.py  # the decision pipeline (Section 10) + dispense
│   └── routers/
│       ├── auth.py
│       ├── prescriptions.py
│       ├── verify.py
│       └── admin.py
├── frontend/                    # Vite + React + TypeScript (Section 13)
│   ├── package.json / vite.config.ts / tsconfig.json
│   ├── openapi.json             # generated by scripts/export_openapi.py
│   ├── e2e/                     # Playwright demo-flow tests + screenshots
│   └── src/
│       ├── main.tsx / App.tsx / routes.tsx
│       ├── styles/              # tokens.css (colour, type, radius, motion), tailwind entry
│       ├── lib/                 # api client (openapi-fetch), auth, csrf, formatters
│       ├── components/ui/       # shadcn/ui components, restyled
│       ├── components/          # Seal, VerificationTimeline, TamperOverlay, RiskGauge, HashChunks, PinRing, AuditChain, RxPreview
│       └── pages/               # Login, Dashboard, NewRx, MyRx, Verify, Admin, Audit
├── data/
│   ├── drugs.csv                # name, generic, is_brand (Indian brands included)
│   ├── drug_reference.csv       # dose limits, schedule per drug
│   ├── interactions.csv         # drug pairs with severity (Tier 1)
│   └── models/                  # iforest.joblib + .sig (git-ignored)
├── scripts/
│   ├── gen_keys.py
│   ├── seed_demo.py             # admin, auditor, 2 doctors (activated), 2 patients, 2 approved pharmacists, expired + revoked samples
│   ├── build_drug_list.py       # optional openFDA pull, falls back to bundled seed list
│   ├── generate_synthetic_data.py
│   ├── train_anomaly.py         # trains, evaluates, writes figures + signed model
│   ├── make_demo_samples.py     # genuine + tampered images/PDFs (see Section 11.2)
│   ├── tamper_audit_demo.py     # 3 modes: edit row, edit+recompute, truncate tail
│   ├── rotate_master_key.py     # re-wraps all DEKs under a new KEK
│   ├── attack_suite.py          # automated attacks + results table (Section 14.3)
│   └── run_dev.ps1              # starts API + Vite dev server on Windows
├── tests/
│   ├── conftest.py              # temp DB, fixed keys, frozen clock
│   ├── test_canonical.py        # incl. hypothesis round-trip properties
│   ├── test_crypto.py
│   ├── test_keys.py
│   ├── test_audit_chain.py
│   ├── test_auth_rbac.py        # full role x endpoint matrix
│   ├── test_activation.py
│   ├── test_issue_and_verify.py
│   ├── test_replay_expiry.py    # incl. concurrent dispense
│   ├── test_qr_parser.py        # fuzz/hypothesis
│   ├── test_pdf_layout.py
│   ├── test_render_diff.py
│   ├── test_ai.py
│   ├── test_pin.py
│   └── test_attack_suite.py
└── docs/
    ├── architecture.md          # Mermaid diagrams: components, issue sequence, verify flow, state machine
    ├── crypto_spec.md           # formal message formats, domain separation, key lifecycle
    ├── threat_model.md          # STRIDE + adversary table (Section 14)
    ├── evaluation.md            # AI metrics, ablation, figures
    ├── api.md                   # exported from FastAPI OpenAPI
    ├── demo_script.md
    └── assumptions.md
```

---

## 6. Data Model (SQLAlchemy)

Internal primary keys are integers. Anything that appears inside a signed payload uses a `public_id` (UUID) so seeds, restores and re-ordering never change signed data.

### `users`
| Column | Type | Notes |
|---|---|---|
| id | int PK | |
| public_id | str unique | UUID4, used in payloads |
| email | str unique | |
| name | str | |
| role | enum | `doctor`, `patient`, `pharmacist`, `admin`, `auditor` |
| password_hash | str nullable | argon2id; null until a doctor activates |
| license_no | str nullable | doctors and pharmacists |
| org_name | str nullable | clinic (doctor) or pharmacy name |
| patient_code | str nullable unique | short code for doctor lookup (patients) |
| approval_status | enum | `APPROVED` (default), `PENDING`, `REJECTED` (pharmacists start `PENDING`) |
| is_active | bool | default true |
| failed_logins | int | default 0 |
| locked_until | datetime nullable | |
| token_version | int | default 0; bump to invalidate all JWTs |
| created_at | datetime | UTC |

### `activation_tokens`
`id, user_id FK, token_sha256, expires_at, used_at nullable`. Token shown once at creation, never stored in plaintext.

### `doctor_keys`
| Column | Type | Notes |
|---|---|---|
| key_id | str PK | first 16 hex of SHA-256 over the public key's SubjectPublicKeyInfo DER |
| user_id | FK users | a doctor may have several keys over time |
| public_key_pem | text | |
| enc_private_key | blob | AES-GCM ciphertext of private key PEM |
| kdf | str | e.g. `pbkdf2-sha256` |
| kdf_salt | blob | 16 bytes |
| kdf_iterations | int | |
| nonce | blob | 12 bytes |
| status | enum | `ACTIVE`, `RETIRED`, `REVOKED` (one ACTIVE per doctor) |
| failed_unlocks | int | wrong signing-password counter |
| unlock_locked_until | datetime nullable | |
| created_at, revoked_at, revoke_reason | | |

### `prescriptions`
| Column | Type | Notes |
|---|---|---|
| id | str PK | UUID4 (`rx_id`) |
| doctor_id, patient_id | FK users | query columns, cross-checked against the payload |
| key_id | FK doctor_keys | |
| payload_enc | blob | `nonce \|\| AES-GCM(canonical payload)`, AAD = `rx_id \|\| b"payload"` |
| payload_hash | str | hex SHA-256 of canonical bytes (kept in clear) |
| signature_b64 | str | base64url raw 64-byte ECDSA signature |
| wrapped_dek | blob | per-prescription DEK wrapped by the KEK |
| kek_version | int | for rotation |
| status | enum | `ISSUED`, `DISPENSED`, `REVOKED` (EXPIRED is **derived**, never stored) |
| max_fills / fills_used | int | `max_fills` is also in the signed payload; cross-checked |
| redeem_secret_wrapped | blob nullable | KEK-wrapped 16-byte secret for PIN derivation |
| require_pin | bool | |
| risk_score | int | issue-time score |
| risk_flags | text (JSON list) | |
| risk_features_json | text | feature snapshot used at issue time (explainability) |
| override_reason | text nullable | doctor's typed reason when issuing despite a warning |
| issued_at, expires_at | datetime | copies of payload values, cross-checked |
| pdf_path | str | encrypted file path (`storage/<rx_id>.pdf.enc`) |
| pdf_sha256 | str | hex hash of the original plaintext PDF |

### `dispenses`
`id, rx_id FK, fill_no int, pharmacist_id FK, ts, UNIQUE(rx_id, fill_no)`. The unique constraint means the database itself refuses a double spend even if application logic has a bug.

### `audit_log`
| Column | Type | Notes |
|---|---|---|
| seq | int PK | strictly increasing from 1 |
| ts | datetime | UTC ISO |
| actor_id | int nullable | |
| actor_role | str nullable | |
| action | str | Section 9 |
| resource_id | str nullable | e.g. rx_id |
| details_json | text | canonical JSON; **IDs and codes only, no names or PII, no secrets** |
| prev_hash | str | hex; genesis = 64 zeros |
| entry_hash | str | hex HMAC-SHA256 (Section 9) |

### `audit_checkpoints`
`id, seq, head_hash, ts, signature_b64`. Also appended as a JSON line to `ANCHOR_FILE`.

### `security_events`
`id, ts, user_id nullable, ip, event_type, severity (LOW/MEDIUM/HIGH), details_json`

### `verification_attempts`
`id, pharmacist_id, rx_id nullable, result, reason_codes (JSON), ts, ip`

---

## 7. Cryptography Design

All code lives in `app/core/`. Every function needs unit tests.

### 7.1 Canonical JSON (`canonical.py`)
Signing requires byte-identical input every time.

```python
def normalise(obj):   # recursively: NFC-normalise every str; reject control chars (Cc/Cf incl. bidi overrides) except \n in notes
def canonical_bytes(obj: dict) -> bytes:
    return json.dumps(normalise(obj), sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")
def sha256_hex(data: bytes) -> str: ...
```

**Prescription payload v2 (what gets signed and what the PDF prints):**

```json
{
  "version": 2,
  "rx_id": "3f0c1b2e-....",
  "key_id": "9a1c0e77b2d4f605",
  "issued_at": "2026-10-18T10:30:00Z",
  "expires_at": "2026-11-17T10:30:00Z",
  "max_fills": 1,
  "doctor":  {"id": "uuid", "name": "Dr. A. Shah", "license_no": "GJ-12345", "clinic": "Shah Clinic, Surat"},
  "patient": {"id": "uuid", "name": "Ravi Patel", "age_years": 34},
  "medicines": [
    {"name": "Amoxicillin", "dose_mg": 500, "frequency": "TDS", "duration_days": 5}
  ],
  "notes": "After food"
}
```

Rules:
- Timestamps are UTC, ISO-8601, `Z` suffix, seconds precision.
- `frequency` is one of `OD`, `BD`, `TDS`, `QID`, `HS`, `SOS` (daily multipliers 1, 2, 3, 4, 1, 3).
- `dose_mg` is an integer in milligrams (documented limitation: no liquids or other units).
- 1-8 medicines (layout limit, Section 13.4). `max_fills` 1-5; forced to 1 if any medicine is controlled.
- The payload is built once at issue time; the exact canonical string is encrypted and stored and never rebuilt from other columns. **Every printed field must come from here (WYSIWYS).**

### 7.2 Doctor keys (`keys.py`)
- **Activation, not admin-set passwords.** At activation the doctor chooses a login password and a different signing password. The server generates an **ECDSA P-256** keypair (`ec.generate_private_key(ec.SECP256R1())`), computes `key_id`, and stores the key as below. The admin never sees either password.
- Serialize the private key to PKCS8 PEM (unencrypted), then **encrypt it ourselves**:
  - `salt = os.urandom(16)`
  - `key = PBKDF2HMAC(SHA256, length=32, salt, iterations=PBKDF2_ITERATIONS).derive(signing_password)` (takes a few hundred ms; that cost is the point)
  - `nonce = os.urandom(12)`; `AESGCM(key).encrypt(nonce, pem, aad=b"pramaan-doctor-key:" + key_id)`
- Store only `public_key_pem`, `enc_private_key`, `kdf`, `kdf_salt`, `kdf_iterations`, `nonce`.
- The private key is decrypted **only in memory, only at signing time**, using the signing password re-entered for each prescription. Drop references immediately after signing. The server never stores the plaintext key or password.
- **Brute-force protection:** a wrong password increments `failed_unlocks`; after `MAX_FAILED_UNLOCKS` the key is locked for `LOCKOUT_MINUTES`. Return a generic 403 and write `SIGN_UNLOCK_FAIL` (and `SIGN_LOCKED` on lockout).
- **Rotation:** doctor calls `POST /keys/rotate` with the current signing password and a new one; a new ACTIVE key is created and the old key becomes RETIRED. Retired keys still verify old prescriptions.
- **Revocation:** an admin may revoke a key (e.g. suspected compromise). Prescriptions signed by a REVOKED key verify as REVOKED while still `ISSUED`. Already `DISPENSED` records stay as history.
- **Trust statement (state it in the deck):** this is *custodial* signing. The server briefly holds the key in memory, so a compromised server plus a phished signing password could forge signatures. Mitigations are the unlock lockout, per-use password entry, audit trail, and rotation. Non-custodial signing is future work (Section 22).

### 7.3 Signing (`crypto.py`)
```python
SIGN_CONTEXT = b"PRAMAAN-RX-v2\x00"        # domain separation: never reused for other message types
def sign(private_key, payload_bytes) -> bytes:       # ECDSA(SHA256) over SIGN_CONTEXT + payload_bytes, returns 64-byte r||s
def verify(public_key, payload_bytes, sig) -> bool:  # False on any failure, never raises on a bad signature
```
Signatures use fixed-size raw `r||s` (via `decode_dss_signature`/`encode_dss_signature`), transported as base64url without padding (86 chars). Audit checkpoints and model signatures use a different key and different context strings (`PRAMAAN-AUDIT-v1\x00`, `PRAMAAN-MODEL-v1\x00`).

### 7.4 Encryption at rest (envelope encryption)
- `MASTER_KEY` (KEK, 32 bytes, from env) never touches disk.
- For each prescription: random 32-byte **DEK**. Encrypt the canonical payload (`payload_enc`) and the PDF (`storage/<rx_id>.pdf.enc`) with AES-256-GCM (`nonce || ciphertext`), using AAD `rx_id || b"payload"` and `rx_id || b"pdf"` respectively. Wrap the DEK with the KEK using AES-GCM (AAD = `rx_id || b"dek" || kek_version`) and store it in `wrapped_dek`.
- **Exact AAD format (as implemented in `app/core/crypto.py`):** `pramaan:<purpose>:<rx_id>` plus `:<kek_version>` for wrapped keys, where purpose is `payload`, `pdf`, `dek` or `redeem`. Signature contexts (each followed by one NUL byte so none is a prefix of another): `PRAMAAN-RX-v2`, `PRAMAAN-AUDIT-v1`, `PRAMAAN-MODEL-v1`. The redeem secret (for the patient PIN) is wrapped the same way as the DEK.
- Using `rx_id` in the AAD means a file or blob cannot be swapped between prescriptions.
- **KEK rotation:** `scripts/rotate_master_key.py` unwraps every DEK with the old KEK and re-wraps it with the new one, incrementing `kek_version`. Ciphertext files are not rewritten. This is the practical reason envelope encryption exists; demo it.
- Precise claim for the deck: *prescription contents and PDFs are encrypted at rest; account metadata (names, emails) is not*, and SQLite itself is not encrypted.
- Decrypt only when an authorised user requests the PDF or a verification needs the payload.

### 7.5 Rules for all crypto code
- `hmac.compare_digest` for every hash/signature/MAC comparison.
- `os.urandom` / `secrets` only for randomness.
- Fresh `os.urandom(12)` nonce for every AES-GCM encryption; never reuse with the same key.
- Unit tests must prove: sign/verify round trip; one flipped bit in payload fails; wrong public key fails; wrong context string fails; wrong signing password fails unlock; AES-GCM tamper fails; swapped AAD fails; canonicalisation is stable under key reordering and rejects bidi/control characters; KEK rotation keeps every prescription decryptable.

---

## 8. Security Design

### 8.1 Authentication and accounts
- Passwords hashed with **argon2id** (`argon2-cffi` defaults), min length 10, validated server-side. Login password and signing password must differ.
- Login returns a **JWT** (HS256; claims `sub`, `iat`, `exp`, `jti`, `tv`=token_version). On **every request** `deps.get_current_user` loads the user from the DB and rejects if inactive, `approval_status != APPROVED`, or `tv` mismatches. Role always comes from the DB, not the token. Logout, password change, and deactivation bump `token_version`.
- Decode with an explicit `algorithms=["HS256"]` and required claims.
- **Lockout:** after `MAX_FAILED_LOGINS` consecutive failures set `locked_until`; reset on success. Unknown email, wrong password and locked account all return the same generic 401 with a similar response time (verify a dummy argon2 hash for unknown emails). Lockout is combined with the per-IP limiter (8.4) so an attacker cannot cheaply lock out a victim.
- Doctor account creation, activation, pharmacist approval, deactivation, and key revocation are audited.

### 8.2 Authorization (RBAC)
`deps.py` exposes `get_current_user` and `require_role("doctor", ...)`. Also enforce **object-level** checks:
- A doctor sees/revokes only prescriptions where `doctor_id == user.id`.
- A patient sees/downloads only where `patient_id == user.id`; the PIN endpoint is patient-only.
- Pharmacists can verify any prescription but only see the minimum fields in Section 10.4.
- Object-level denial returns `404`, not `403`, so existence is not leaked.
- `tests/test_auth_rbac.py` builds an automatic role x endpoint matrix; adding an endpoint without a matrix entry fails the test.

### 8.3 Replay, expiry, revocation, and patient consent
**State machine:** `ISSUED -> DISPENSED` (when `fills_used == max_fills`), `ISSUED -> REVOKED`. Only `ISSUED` can be revoked. `EXPIRED` is derived from the signed payload's `expires_at` at check time and is never a stored state.

**Atomic dispense (inside one transaction with the audit entry):**
```sql
UPDATE prescriptions
SET fills_used = fills_used + 1,
    status = CASE WHEN fills_used + 1 >= max_fills THEN 'DISPENSED' ELSE 'ISSUED' END
WHERE id = :id AND status = 'ISSUED' AND fills_used < max_fills AND expires_at > :now;
-- rowcount == 0 => return the precise reason (used / revoked / expired)
INSERT INTO dispenses (rx_id, fill_no, pharmacist_id, ts) VALUES (:id, :fills_used_after, :pid, :now);
-- UNIQUE(rx_id, fill_no) makes a double spend impossible even under a logic bug
```
`expires_at` here is the *column*, which is cross-checked against the signed payload in the verification step that runs first inside the same transaction (10.3).

**Expiry:** default 30 days, configurable per prescription (max 90). Verification is **read-only**; only `/dispense` consumes a fill.

**Patient-consent PIN (`pin.py`, Tier 1):**
- At issue, generate a 16-byte `redeem_secret` and store it KEK-wrapped.
- PIN = 6 digits from `HMAC-SHA256(redeem_secret, rx_id || floor(now / PIN_STEP_SECONDS))` using RFC 4226-style dynamic truncation. Accept the current and previous step.
- The registered patient sees the PIN in their app (`GET /prescriptions/{id}/pin`). The pharmacist enters it at dispense. A stolen photo or PDF without the patient's phone cannot be dispensed.
- 3 wrong PINs per prescription within 5 minutes locks PIN attempts for that prescription and raises a MEDIUM security event.
- If the patient has no account, the doctor sets `require_pin=false` and the pharmacist must tick an explicit "patient identity checked" box (recorded in the audit entry).

### 8.4 Rate limiting and alerting (`events.py`)
- In-memory sliding-window limiter (`slowapi` was dropped: the per-account key needs the request body): login `5/minute` per IP **and** per target account; verify endpoints `30/minute` per user (custom `key_func` reading the JWT subject); PIN attempts as above.
- **Real client IP:** the browser calls FastAPI directly (same origin), so the peer address is the real client. `X-Forwarded-For` is honoured **only** if the immediate peer is listed in `TRUSTED_PROXY_IPS` (empty by default).
- Alert rules (write a `security_events` row + an audit `SECURITY_ALERT` entry):
  - >= 5 failed verifications (TAMPERED / NOT_FOUND / INVALID_QR) by one pharmacist in 10 minutes => HIGH
  - >= 5 failed logins for one account => MEDIUM
  - Verification of a DISPENSED prescription by a pharmacist other than the one who dispensed it => MEDIUM (possible replay)
  - Scans of one prescription by >= 3 distinct pharmacists => MEDIUM (`MULTI_PHARMACY_SCANS`)
  - Wrong PIN lockout => MEDIUM
  - Signing-password lockout => MEDIUM
  - Doctor issued despite a high-risk warning => LOW, admin sees it in the list
  - Audit chain verification failure => HIGH

### 8.5 Hardening checklist
- **Fail-closed startup:** `config.py` rejects missing/placeholder `SECRET_KEY` (< 32 bytes), `MASTER_KEY`/`AUDIT_KEY` that do not base64-decode to 32 bytes, or a missing audit signing key, and exits with a clear message.
- Strict Pydantic validation on every input (length limits, enums, ranges); no raw dicts crossing router boundaries.
- Upload limits: images/PDF only, max 5 MB, check magic bytes not just extension, cap decoded image dimensions, PDF page count <= 3, never execute or parse embedded JavaScript/attachments.
- Security headers middleware: `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, `Cache-Control: no-store` on authenticated responses.
- CORS restricted to `CORS_ORIGINS`. OpenAPI docs disabled unless `DEBUG=true`.
- Generic client errors; details only in server logs (never secrets or PII).
- No raw SQL string concatenation (SQLAlchemy parameters only).
- Secrets only from environment or the `secrets/` directory; never in the DB or git.
- CI runs `bandit` and `pip-audit`; a `detect-secrets` or manual grep step checks for committed keys.
- Optional: run uvicorn with a local TLS cert (mkcert) for the demo; otherwise state "no TLS" as a limitation.

---

## 9. Tamper-Evident Audit Log (`audit.py`)

Each entry is chained to the previous one with a **keyed** hash, so a database insider who lacks `AUDIT_KEY` cannot recompute it.

```
entry_hash = HMAC_SHA256( AUDIT_KEY,
    prev_hash || canonical_json({"seq", "ts", "actor_id", "actor_role", "action", "resource_id", "details"}) )
```

- Genesis `prev_hash` = `"0" * 64`.
- `append(db, actor, action, resource_id, details)` takes the **caller's session** and does not commit: the audit row and the business change commit or roll back together. The DB engine issues `BEGIN IMMEDIATE` for write transactions (SQLAlchemy event hook) so `seq` is assigned under the write lock; enable WAL and `busy_timeout`.
- **Checkpoints:** every 50 entries (and on demand via `POST /admin/audit/checkpoint`, auditor role) sign `seq || head_hash` with the audit ECDSA key (context `PRAMAAN-AUDIT-v1`), store it in `audit_checkpoints`, and append a JSON line to `ANCHOR_FILE`. In a real deployment that file goes to an external write-once store; in the demo it is a separate file, which is enough to show the idea.
- `verify_chain(db) -> {"ok", "checked", "first_bad_seq", "checkpoint_ok", "truncated"}`:
  1. recompute every HMAC in order => detects edits and re-ordering;
  2. verify each checkpoint signature and that the row at `seq` has the recorded `head_hash` => detects recomputation by someone with only a plain SHA-256;
  3. confirm the log's last `seq` >= the last checkpoint's `seq` and compare with `ANCHOR_FILE` => detects truncation.
- **Never** put passwords, keys, tokens, PINs, names, or document contents into `details`. Use IDs and codes only (this also lets personal data be erased without breaking the chain).

**Action names:** `USER_REGISTER`, `ACCOUNT_ACTIVATED`, `PHARMACIST_APPROVED`, `PHARMACIST_REJECTED`, `LOGIN_SUCCESS`, `LOGIN_FAIL`, `LOGOUT`, `ACCOUNT_LOCKED`, `KEY_GENERATED`, `KEY_ROTATED`, `KEY_REVOKED`, `SIGN_UNLOCK_FAIL`, `SIGN_LOCKED`, `RX_ISSUED`, `RX_ISSUED_WITH_OVERRIDE`, `RX_REVOKED`, `RX_PDF_DOWNLOADED`, `RX_PIN_VIEWED`, `RX_VERIFIED`, `RX_VERIFY_FAILED`, `RX_DISPENSED`, `PIN_FAIL`, `SECURITY_ALERT`, `ADMIN_USER_CREATED`, `ADMIN_USER_DEACTIVATED`, `AUDIT_VERIFIED`, `AUDIT_CHECKPOINT`, `KEK_ROTATED`.

**Demos (`scripts/tamper_audit_demo.py --mode`):**
- `edit`: changes one row's `details_json` => `ok=false`, correct `first_bad_seq`.
- `recompute`: edits a row and recomputes later hashes using plain SHA-256 => still fails (wrong HMAC).
- `truncate`: deletes the last N rows => `truncated=true` via checkpoint/anchor.

---

## 10. Verification Pipeline (`verification_service.py`)

### 10.1 QR format (`qr.py`)
```
PRM2.<rx_id>.<key_id>.<payload_hash_hex>.<signature_b64url>
```
About 210 characters; fits comfortably in a QR at error correction level M (even a version-10 symbol is much smaller than the maximum). `parse_qr(s)` strictly validates the prefix, UUID, 16-hex key id, 64-hex hash and 86-char base64url signature, rejects trailing garbage and whitespace tricks, and raises a clear error otherwise.

### 10.2 Decision steps (in this exact order)

```
Input: qr_string (scan/paste) OR uploaded file (image/PDF)

1. If file: render PDF page 1 with PyMuPDF if PDF; decode QR (QRCodeDetectorAruco, then
   fallbacks: upscale, grayscale, adaptive threshold). No QR => INVALID_QR.
2. parse_qr() => rx_id, qr_key_id, qr_hash, qr_sig. Malformed => INVALID_QR.
3. Load prescription by rx_id. Not found => NOT_FOUND (+ failed-verification counter).
4. Decrypt payload_enc with the DEK. AES-GCM failure => TAMPERED (DB_RECORD_ALTERED).
   Recompute sha256 of the payload and compare (constant time) with:
     a) stored payload_hash -> mismatch => TAMPERED (DB_RECORD_ALTERED)
     b) qr_hash             -> mismatch => TAMPERED (QR_HASH_MISMATCH)
5. Load key by payload.key_id; it must equal qr_key_id (else TAMPERED, KEY_ID_MISMATCH).
   Verify ECDSA over SIGN_CONTEXT+payload with that public key. Invalid, or qr_sig != stored
   signature => TAMPERED (INVALID_SIGNATURE).
6. Cross-check mutable columns against the SIGNED payload: doctor, patient, key_id, issued_at,
   expires_at, max_fills. Any mismatch => TAMPERED (DB_RECORD_ALTERED). From here on use
   payload values, not columns.
7. Key/doctor state: key REVOKED, or doctor suspended => REVOKED (reason DOCTOR_KEY_REVOKED /
   DOCTOR_SUSPENDED). RETIRED key is fine.
8. If a file was uploaded: render-and-diff + OCR (Section 11.2).
     any zone MISMATCH, EXTRA content, or HIDDEN_TEXT_OR_OVERLAY => TAMPERED (CONTENT_MISMATCH)
     any critical zone UNREADABLE (dose, frequency, duration, patient name) => REVIEW_REQUIRED
9. Status checks (state from DB, expiry from payload):
     status == REVOKED                      => REVOKED
     fills_used >= max_fills / DISPENSED    => ALREADY_USED
     now > payload.expires_at               => EXPIRED
10. Risk (Section 11.6): stored issue-time score plus new signals since issue.
     score >= RISK_THRESHOLD                => SUSPICIOUS
11. Otherwise => VALID
```

**Precedence:** `TAMPERED > REVOKED > ALREADY_USED > EXPIRED > SUSPICIOUS > REVIEW_REQUIRED > VALID`. `NOT_FOUND` and `INVALID_QR` end the pipeline early. All applicable reason codes are returned even when only the top result is displayed.

Optional bonus: if an uploaded PDF's SHA-256 equals `pdf_sha256`, set `file_integrity="ORIGINAL"`; if it differs but zones match (photo/print), `"REPRODUCTION"`. Informational only.

### 10.3 Dispense re-verification
`POST /prescriptions/{id}/dispense` takes `qr_string` (proof of possession), optional `patient_pin`, and `patient_identity_checked`. Inside **one transaction** it re-runs steps 2-7 and 9 (hash, signature, key state, status, expiry), checks the PIN if `require_pin`, performs the atomic update and `dispenses` insert (Section 8.3), and appends the `RX_DISPENSED` audit entry. A verification result shown earlier is never trusted at dispense time.

### 10.4 Response schema

```json
{
  "result": "VALID",
  "reason_codes": [],
  "rx_id": "3f0c1b2e-...",
  "checks": {
    "signature_valid": true, "hash_match": true, "key_state": "ACTIVE",
    "doctor_active": true, "status": "ISSUED", "fills_remaining": 1,
    "not_expired": true, "content_check": "MATCH", "file_integrity": "ORIGINAL"
  },
  "content_zones": [
    {"zone": "med_0_dose", "signed": "500", "read": "500", "status": "MATCH", "bbox": [x, y, w, h]}
  ],
  "risk": {"score": 12, "flags": [], "explanations": []},
  "warnings": [],
  "doctor": {"name": "Dr. A. Shah", "license_no": "GJ-12345"},
  "patient": {"name": "R. Patel"},
  "medicines": [{"name": "Amoxicillin", "dose_mg": 500, "frequency": "TDS", "duration_days": 5}],
  "issued_at": "...", "expires_at": "...",
  "can_dispense": true, "pin_required": true
}
```

Data minimisation: `NOT_FOUND`/`INVALID_QR` return no prescription data. Patient shown as initial + surname. `content_zones` appears only for uploads. Every verification writes a `verification_attempts` row and an audit entry (`RX_VERIFIED` or `RX_VERIFY_FAILED`).

---

## 11. AI Module

### 11.1 OCR (`ocr.py`)
```python
class OCREngine(Protocol):
    def read(self, image: np.ndarray) -> list[OCRLine]   # text, confidence, bbox

class RapidOCREngine: ...    # lazy-load once; models are bundled in the pip wheel
```
Preprocess: grayscale, resize if width < 1000 px, mild denoise. `EasyOCREngine`/`TesseractEngine` are optional adapters, not required for any acceptance test.

### 11.2 Content verification: render-and-diff + OCR (`rectify.py`, `render_diff.py`)
Why: OCR on a photo can misread a *genuine* digit and wrongly accuse an honest doctor, and a free-form OCR comparison cannot say *where* an edit is. Since we know exactly what a genuine document looks like, we compare images rather than trusting OCR to read every digit.

1. **Fiducials.** `pdf_layout.py` places the QR code plus three small corner markers (simple L-shaped or ArUco-style marks) at known page coordinates.
2. **Rectify.** Detect the QR corners and markers, compute a homography, and warp the upload to the canonical page raster (A4 at 200 dpi). Record an *alignment quality* score. If fewer than 4 anchors are found (heavy crop/blur), fall back to full-page OCR with fuzzy line matching and downgrade every uncertain field to UNREADABLE.
3. **Render expected.** `pdf.py` renders the expected page from the *signed payload* with the identical layout engine; rasterise to the same size.
4. **Per-zone diff.** For each zone in `pdf_layout.py` (`clinic`, `doctor_block`, `patient_block`, `dates`, `med_i_name/dose/freq/days` for i in 0-7, `notes`, `fingerprint`): binarise both crops, compute a tolerance-aware similarity (e.g. SSIM or normalised correlation after a small shift search). **Unused medicine rows and margins must be blank**; ink there means `EXTRA_CONTENT`.
5. **OCR second opinion.** OCR each differing zone and apply Section 11.3 extraction to produce the human-readable "document reads 800 mg".
6. **Decision matrix (per zone):**

| Diff says | OCR says | Alignment | Zone status |
|---|---|---|---|
| similar | (any) | any | `MATCH` |
| differs | reads a *different* value, conf >= 0.8 | any | `MISMATCH` => TAMPERED |
| differs | low confidence / nothing | good (clean digital render) | `MISMATCH` => TAMPERED |
| differs | low confidence / nothing | poor (photo) | `UNREADABLE` => REVIEW_REQUIRED |
| blank expected, ink found | | any | `EXTRA_CONTENT` => TAMPERED |

7. **PDF spoofing check:** for PDF uploads also read the text layer. If the text layer disagrees with the rendered page in any zone (white-box overlay, hidden text) => TAMPERED (`HIDDEN_TEXT_OR_OVERLAY`). The text layer is never trusted alone.
8. **Output:** per-zone status with `bbox`, so the UI can draw a red box over the altered cell.

**Spike first (start of Phase 7):** prove rectification + diff on 10 sample photos/screenshots (various angles and lighting) before building the rest. If it cannot reach the acceptance rates in Section 15 P7, fall back to OCR-only comparison (the original v1 method) for the zones it can read, mark the rest UNREADABLE, and document the result honestly.

### 11.3 Extraction and drug validation (`extract.py`, `drug_match.py`)
Extraction (regex, no heavy NLP):
- Dose `(\d{1,5})\s*(mg)\b`; frequency `\b(OD|BD|TDS|QID|HS|SOS)\b` plus patterns such as `1-0-1` (BD), `1-1-1` (TDS); duration `(\d{1,3})\s*(days?|d)\b`.
- Return `list[ExtractedMedicine(name, dose_mg|None, frequency|None, duration_days|None, confidence)]`.

Drug validation:
- `data/drugs.csv`: columns `name, generic, is_brand` (generic names plus common Indian brands such as Dolo, Crocin, Augmentin). `scripts/build_drug_list.py` may pull from openFDA and must fall back to a bundled seed list of >= 100 names when offline.
- `match_drug(name) -> (best_name, score, generic)`: **exact case-insensitive match first** (score 100). Otherwise `rapidfuzz.process.extractOne` with `fuzz.WRatio`, but names shorter than 5 characters never fuzzy-match (prevents "Pan" matching everything).
  - exact (after normalising away dosage-form words and strengths) => known drug
  - **as built:** any non-exact name that is at least 75% similar (`fuzz.ratio`) => `POSSIBLE_TYPO` with the suggested spelling, because one changed letter can be a different drug; names under 5 characters are exact-only
  - no close match => `UNKNOWN_DRUG`
- `data/drug_reference.csv` columns: `name, max_single_dose_mg, max_daily_dose_mg, schedule` where `schedule` is `OTC`, `H`, `H1`, `X` (illustrative groupings inspired by India's Drugs and Cosmetics Rules; **not legal or clinical guidance**). Schedule H1 and X count as "controlled" for scoring.

Seed examples (demo values only):

```
name,max_single_dose_mg,max_daily_dose_mg,schedule
Paracetamol,1000,4000,OTC
Ibuprofen,800,3200,OTC
Amoxicillin,1000,3000,H
Azithromycin,500,500,H
Cetirizine,10,10,OTC
Omeprazole,40,40,H
Metformin,1000,2550,H
Atorvastatin,80,80,H
Amlodipine,10,10,H
Tramadol,100,400,H1
Alprazolam,2,4,H1
```
Create at least 40 rows.

- `dose_check(name, dose_mg, frequency) -> flags`: `DOSE_ABOVE_SINGLE_MAX`, `DOSE_ABOVE_DAILY_MAX` (`dose_mg * multiplier > max_daily`), `CONTROLLED_SUBSTANCE` (schedule H1/X).

### 11.4 Interaction rules (`interactions.py`, Tier 1)
`data/interactions.csv`: `drug_a, drug_b, severity (MODERATE|MAJOR), note`, >= 15 well-known pairs (e.g. NSAID + anticoagulant, two serotonergic agents). Flags `INTERACTION_MODERATE` / `INTERACTION_MAJOR`. Display the disclaimer: demo data, not clinical advice. Also flag `DUPLICATE_THERAPY` for the same generic twice.

### 11.5 Anomaly model (`features.py`, `anomaly.py`, `scripts/train_anomaly.py`)
- Algorithm: **Isolation Forest** (`n_estimators=200`, fixed `random_state=42`), trained on normal data only.
- Features (built by one function used for both training and inference):
  1. `num_medicines`
  2. `max_daily_dose_ratio` (daily dose / max daily dose, max across medicines)
  3. `max_duration_days`
  4. `controlled_count`
  5. `doctor_rx_last_24h`
  6. `issue_hour`
  7. `patient_rx_last_7d`
  8. `new_drug_ratio_for_doctor` (share of medicines this doctor has never prescribed before; **per-doctor baseline**, catches stolen credentials and rogue behaviour)
  9. `controlled_ratio_doctor_30d` (this doctor's recent controlled share vs. their norm)
  10. `distinct_patients_last_24h`
- **Training data** (`scripts/generate_synthetic_data.py`): ~5,000 normal rows generated from per-doctor profiles (specialty-specific drug mixes, working hours). Anomalies come in **families**: *tuning set* (huge doses, 10+ medicines, 3 AM controlled bursts) and an **unseen test set** (e.g. specialty switch, many new patients in an hour, slow low-dose controlled drip). Never tune on the unseen family.
- **Evaluation** (writes `docs/evaluation.md` and figures to `docs/evaluation/`): ROC-AUC and PR-AUC on the unseen family; precision/recall/F1 at the production threshold; confusion matrix; an **ablation** (rules only / IF only / combined); and a **model comparison** (Isolation Forest vs. Local Outlier Factor vs. One-Class SVM). State plainly that data is synthetic, so metrics demonstrate the method, not real-world accuracy.
- **Score:** `anomaly_score(features) -> float in [0,1]` computed as the percentile of `-decision_function` against the training score distribution (clipped), so 0.5 is median-normal and 0.95+ is rare. Save the percentile table with the model.
- **Explanations:** for each feature, report its percentile within the normal training data; the top-2 features beyond the 99th percentile produce text like "Doctor prescribed 12 controlled-drug items in 24 h (normal: <= 3)". Deterministic and fast; no extra dependency.
- If the model file is missing or its signature fails (11.7), degrade gracefully to rules-only and add `MODEL_UNAVAILABLE` to warnings (never crash).

### 11.6 Combined risk (`risk.py`)
```
risk = min(100, rule_points + round(anomaly_score * 40))
```
| Rule | Points |
|---|---|
| UNKNOWN_DRUG | +60 (equal to the review threshold, so a name not in the drug list always needs a second look) |
| POSSIBLE_TYPO | +15 |
| DOSE_ABOVE_SINGLE_MAX | +35 |
| DOSE_ABOVE_DAILY_MAX | +35 |
| CONTROLLED_SUBSTANCE | +10 each (cap +20) |
| INTERACTION_MAJOR / MODERATE | +20 / +8 |
| DUPLICATE_THERAPY | +10 |
| DOCTOR_BURST (>= 15 rx in 24 h) | +20 |
| MULTI_PHARMACY_SCANS (verify-time only) | +15 |

Return `RiskResult(score:int, flags:list[str], explanations:list[str], features:dict)`. Always provide human-readable explanations (UI and deck).

**Where it runs:**
- **Issue time:** compute and store score, flags, and the feature snapshot. If `risk >= RISK_THRESHOLD`, the doctor sees a warning and must type an override reason to proceed; this is stored, audited (`RX_ISSUED_WITH_OVERRIDE`), and shown to admins as a LOW event. **No hard block** (a hard block would also block legitimate unusual care and contradict the demo).
- **Verify time:** deterministic, no re-training or re-scoring from "current history": use the stored issue-time score and add only *new* signals since issue (`MULTI_PHARMACY_SCANS`, doctor key/state flags).

### 11.7 Model file integrity (`model_io.py`)
`joblib`/pickle files execute code when loaded. `train_anomaly.py` writes `iforest.joblib` plus `iforest.joblib.sig` (ECDSA over the file's SHA-256, context `PRAMAAN-MODEL-v1`, audit signing key). `load_model()` verifies the signature **before** `joblib.load`; failure => `MODEL_UNAVAILABLE` + a HIGH security event.

---

## 12. API Specification

Base URL `http://localhost:8000/api` (every path below is relative to `/api`). JSON except uploads/downloads. Browser auth is an `HttpOnly` session cookie plus an `X-CSRF-Token` header on state-changing requests (Section 13.0); scripts and tests may use `Authorization: Bearer <jwt>` instead. Standard errors: `400` validation, `401` unauthenticated (also locked/unknown), `403` forbidden (role), `404` not found (also object-level denial), `409` conflict (state), `413` file too large, `429` rate limited.

### Auth
| Method | Path | Role | Description |
|---|---|---|---|
| POST | `/auth/register` | public | `patient` or `pharmacist` only (pharmacist => PENDING) |
| POST | `/auth/activate` | public | Doctor: `{email, token, login_password, signing_password}`; creates key |
| POST | `/auth/login` | public | Returns `{access_token, token_type, role, name}` |
| POST | `/auth/logout` | any | Bumps `token_version` |
| GET | `/auth/me` | any | Current user |
| POST | `/auth/change-password` | any | Bumps `token_version` |

### Keys
| Method | Path | Role | Description |
|---|---|---|---|
| POST | `/keys/rotate` | doctor | Needs current + new signing password |
| GET | `/keys/mine` | doctor | List own keys (status, key_id) |

### Prescriptions
| Method | Path | Role | Description |
|---|---|---|---|
| POST | `/prescriptions` | doctor | Body: `patient_id`, `medicines[]`, `notes`, `validity_days`, `max_fills`, `signing_password`, `override_reason?`, `require_pin?`. Builds payload, risk, signs, makes QR + PDF, encrypts, stores. Returns `rx_id`, `risk`, `warnings`. If risk >= threshold and no override reason => `409` with the risk details (client re-submits with a reason). |
| GET | `/prescriptions/mine` | doctor, patient | List own |
| GET | `/prescriptions/{id}/pdf` | owner doctor, owner patient | Decrypt and stream; audit `RX_PDF_DOWNLOADED` |
| GET | `/prescriptions/{id}/pin` | owner patient | Current dispense PIN; audit `RX_PIN_VIEWED` |
| POST | `/prescriptions/{id}/revoke` | owner doctor | Sets `REVOKED` (conditional UPDATE) |
| GET | `/patients/lookup?email=` or `?code=` | doctor | **Exact** match only; returns `id` + name |

### Verification
| Method | Path | Role | Description |
|---|---|---|---|
| POST | `/verify/qr` | pharmacist | `{qr_string}`; runs steps 2-7, 9-11 |
| POST | `/verify/upload` | pharmacist | Multipart image/PDF; runs steps 1-11 |
| POST | `/prescriptions/{id}/dispense` | pharmacist | `{qr_string, patient_pin?, patient_identity_checked?}`; atomic (10.3) |

### Admin / Audit
| Method | Path | Role | Description |
|---|---|---|---|
| POST | `/admin/users` | admin | Create doctor; returns one-time activation token |
| GET | `/admin/users?status=` | admin | List, incl. pending pharmacists |
| POST | `/admin/users/{id}/approve` or `/reject` | admin | Pharmacist approval |
| PATCH | `/admin/users/{id}/deactivate` | admin | Suspend: deactivate + revoke keys for doctors; bumps token_version |
| POST | `/admin/keys/{key_id}/revoke` | admin | `{reason}` |
| GET | `/admin/audit?limit=&offset=` | auditor | Paginated audit log |
| GET | `/admin/audit/verify` | auditor | Runs `verify_chain` |
| POST | `/admin/audit/checkpoint` | auditor | Signed checkpoint |
| GET | `/admin/security-events` | admin, auditor | Recent alerts |
| GET | `/health` | public | Liveness only, no details |

---

## 13. Frontend (React + TypeScript, premium design)

Streamlit was dropped: it cannot deliver a sharp, premium, fully controlled UI or a live camera QR scanner. The frontend is a **Vite + React 18 + TypeScript** single-page app in `frontend/`.

### 13.0 Stack and wiring
| Concern | Choice |
|---|---|
| Build | Vite, TypeScript (strict), npm (Node 20.19+ or 22+; this machine has Node 24) |
| Styling | **Tailwind CSS v4** with design tokens as CSS variables; light + dark themes |
| Components | **shadcn/ui** (Radix primitives copied into `frontend/src/components/ui`, so we own and restyle them) |
| Motion | `motion` (Framer Motion); respect `prefers-reduced-motion` |
| Data | TanStack Query; API types generated from FastAPI's OpenAPI via `openapi-typescript` + `openapi-fetch` (`scripts/export_openapi.py` dumps `frontend/openapi.json`, so the contract cannot drift) |
| Routing / forms | React Router; react-hook-form + zod |
| Charts | Recharts (risk gauge, evaluation figures in the admin view) |
| Icons / toasts | lucide-react, sonner |
| QR scanning | `qr-scanner` (live camera scanning in the browser; no longer a stretch item) |
| Fonts | Self-hosted via `@fontsource` packages (no CDN, works offline): a refined sans for UI, a serif display face for headings, a mono face for hashes/IDs |
| Tests | Vitest for components, **Playwright** for end-to-end demo flows and automated screenshots |

**Serving:** in development, Vite runs on `:5173` and proxies `/api` to FastAPI on `:8000`. In production, `npm run build` produces `frontend/dist`, and FastAPI serves it with an SPA fallback, so the whole app is **one origin on one port** (`uvicorn app.main:app`). All API routes live under the `/api` prefix (the paths in Section 12 are relative to `/api`).

**Session security (replaces bearer tokens in the browser):**
- Login sets the JWT in an `HttpOnly`, `SameSite=Strict` cookie (`Secure` when TLS is on). JavaScript never sees it, so XSS cannot steal it.
- CSRF defence: double-submit token. A readable `csrf` cookie is echoed in an `X-CSRF-Token` header on every state-changing request; FastAPI rejects mismatches. `Authorization: Bearer` is still accepted for scripts and tests (attack suite). As built, the token is an HMAC of the session id (`jti`) that the server recomputes and compares, so it cannot be forged or planted from another origin and needs no storage.
- Strict CSP from FastAPI: `default-src 'self'; script-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'` (inline styles only because of animation libraries).
- No `dangerouslySetInnerHTML`; all user text is rendered through React's escaping. Uploaded images are shown via `blob:` URLs only.
- Because the browser now talks to FastAPI directly, the server sees the real client IP, so the proxy-header plumbing from v2 is not needed.

### 13.1 Design direction ("a seal of proof")
The brand idea is *proof*: official, calm, exact. The product should feel like a modern certificate authority crossed with a clinical instrument, not a dashboard template.

- **Palette (as built, OKLCH tokens in `frontend/src/index.css`):** white surfaces on a cool near-white canvas (a hair of chroma toward the ink hue, not warm, to avoid the cream/paper cliche), deep ink navy for text and primary actions; dark theme uses near-black blue-grey. One signature accent (deep teal-green) reserved for *verified* states. Semantic colours: red = tampered/revoked/not found/invalid QR, amber = caution, never decorative. No gradients, no glassmorphism. Restrained colour strategy: accent only on state and primary actions.
- **Typography (as built):** Inter Variable for all UI text; Source Serif 4 Variable for page titles, the brand wordmark and verdict headings only (never labels or buttons); JetBrains Mono Variable with tabular figures for hashes, IDs and PINs. Fixed rem scale (about 1.2 ratio), no fluid type. Hashes shown in grouped chunks (`9a1c 0e77 b2d4 f605`).
- **Shape and depth:** 4/6/8 px radii, 1 px hairline borders instead of heavy shadows, a second neutral layer for sidebar and wells, dense but readable tables. The verdict **seal** (stamped ring with edge ticks) is the memorable detail; it is reused as a large low-opacity watermark on the sign-in brand panel.
- **Motion (product register):** 150-250 ms transitions that convey state only, no orchestrated page-load sequences; the seal ring draws once when a verdict arrives; `prefers-reduced-motion` shows final states instantly. Design context lives in `PRODUCT.md`.
- **Signature moments (build these first):**
  1. **Verification theatre:** after a scan, the pipeline steps (QR parsed, hash match, signature, key state, status, content, risk) tick off one by one with a short stagger, then the **seal** (animated ring + icon) settles into the final verdict. Reduced-motion users get the final state instantly.
  2. **Tamper overlay:** the uploaded image with a red box on the altered cell and callouts "Signed 500 mg / Document reads 800 mg".
  3. **Issue split view:** form on the left, a live WYSIWYS prescription preview on the right that updates as the doctor types.
  4. **Audit chain view:** entries drawn as linked blocks; on a failed check the chain visibly breaks at `first_bad_seq` and the checkpoint markers show as anchors.
  5. **Patient PIN:** large mono digits inside a countdown ring that refreshes each PIN step.
- **Accessibility:** WCAG AA contrast, visible focus rings, keyboard-navigable, colour is always paired with icon + text, `aria-live` on verification results.
- **Responsive:** pharmacist verify flow must work on a phone-width screen (camera scanning); other pages desktop-first but usable on tablet.

### 13.2 Pages
| Page | Role | Features |
|---|---|---|
| Login / Register / Activate | public | Split layout with brand panel; activation-token form for doctors; password strength meter |
| Dashboard | all | Role-specific summary (issued today / pending / alerts) |
| New Prescription | doctor | Exact patient lookup, repeatable medicine rows (autosuggest from `drugs.csv`), notes, validity, max fills, signing password, **risk panel** with explanations and a required override-reason box, live PDF/QR preview, download |
| My Prescriptions | doctor, patient | Filterable table with status badges; PDF download; doctor can revoke; patient sees the **PIN** with countdown |
| Verify | pharmacist | Tabs: **Scan** (live camera via `qr-scanner`), **Upload** (drag-and-drop image/PDF), **Paste QR text**. Verification theatre, verified-record card, checks list, risk gauge + explanations, tamper overlay, **Dispense** panel (PIN field / identity checkbox) shown only when `can_dispense` |
| Admin | admin | Users table, pharmacist approvals, activation-token dialog (shown once, copy button), key revocation, security events |
| Audit | auditor | Audit table, chain view, "Verify chain" pass/fail banner, checkpoint button, anchor status |
| Command palette (optional) | all | `Ctrl+K` navigation (cmdk) if time allows |

### 13.3 Result presentation rules
- Colour **plus** icon and text (never colour alone): green VALID, red TAMPERED / REVOKED, amber EXPIRED / ALREADY_USED / SUSPICIOUS / REVIEW_REQUIRED.
- Always show the **verified record** prominently with the line: "Dispense according to this verified record, not the paper."
- For content mismatches, draw the red box over the `bbox` on the uploaded image and show "Signed: 500 mg / Document reads: 800 mg".
- Footer on every page: "Academic demo. Not for clinical use."

### 13.4 Prescription PDF layout (`pdf_layout.py`, `pdf.py`)
A4 portrait. **`pdf_layout.py` is the only place that defines positions**; both the PDF generator and the verifier import it.
- Header: clinic name. Doctor name + licence. Patient name (+ age). Issue date and validity. Max fills.
- Medicines table: up to 8 fixed rows (name, dose, frequency, days); unused rows stay empty.
- Notes box. QR bottom-right (~3.5 cm) with caption "Scan with Pramaan to verify". Footer with `rx_id` and a short fingerprint (first 12 hex of the payload hash, grouped 4-4-4).
- Three corner fiducial marks at fixed positions.
- All visible text comes from the signed payload. Use a clear sans-serif font, at least 11 pt. The reportlab output must be deterministic (set invariant mode) so `pdf_sha256` and zone diffs are stable.

---

## 14. Threat Model

### 14.1 STRIDE (`docs/threat_model.md`)

| Threat | Example | Mitigation |
|---|---|---|
| **S**poofing | Fake doctor; fake pharmacist | Admin-only doctor creation + activation token, per-doctor ECDSA key, pharmacist approval, argon2, JWT revoked via `token_version`, lockout |
| **T**ampering | Edit dose on PDF/photo; edit DB row | Signed payload (WYSIWYS), render-and-diff, QR hash check, AES-GCM integrity, signed-payload cross-checks |
| **R**epudiation | Doctor denies issuing; pharmacist denies dispensing | Digital signature, HMAC-chained audit log with signed checkpoints, `dispenses` table |
| **I**nformation disclosure | Stolen DB or storage dir; over-broad lookups | Envelope encryption of payload + PDF, password-protected private keys, data minimisation, exact-match patient lookup, RBAC |
| **D**enial of service | Flood verify endpoint; lock out a victim | Rate limiting (account + IP), upload limits, per-IP throttle before lockout |
| **E**levation of privilege | Pharmacist calls doctor endpoints; admin reads audit | `require_role`, object-level checks, role x endpoint test matrix, separate auditor role |
| Replay | Same prescription at many pharmacies | Atomic dispense, `UNIQUE(rx_id, fill_no)`, expiry, cross-pharmacy alerts |
| Stolen/photographed prescription | Someone else redeems | Patient-consent PIN, QR required as possession proof |
| Insider abuse | DBA edits records or logs | Encrypted+signed payloads, HMAC chain, signed checkpoints, external anchor |

### 14.2 Adversary view
Complement the STRIDE table with the four adversaries in Section 1.1 (forger, abuser, authenticated-abnormal, insider) and show which control stops each. Also document honestly what is **out of scope**: no HSM, no TLS in the local demo, SQLite is not production-grade, custodial signing, no real regulatory compliance, no protection against a fully compromised server holding the KEK and audit key.

### 14.3 Attack suite (`scripts/attack_suite.py`)
Runs against a seeded local instance and prints a table `Attack | Control that caught it | Result`. Each attack is also a pytest in `tests/test_attack_suite.py`. Required attacks:

1. Flip one bit of the payload in the DB
2. Change `expires_at` column to extend validity
3. Edit one dose digit in a rendered image
4. White-box overlay on PDF text layer
5. Add an extra medicine line below the table
6. Forge one character of the QR signature
7. Swap QR from another prescription
8. Replay the same QR at a second pharmacist
9. Concurrent double-dispense (20 threads)
10. Redeem with a photographed QR but no/wrong PIN
11. Brute-force login (lockout + 429)
12. Brute-force the signing password
13. Use a JWT after logout/deactivation
14. Pharmacist calls doctor/admin endpoints
15. Edit an audit row; edit-and-recompute; truncate the tail
16. Swap the anomaly model file (signature check)

---

## 15. Build Plan (phases with acceptance criteria)

Run `pytest -q` at the end of every phase. Commit messages: `phase-N: short description`. From P4 on, every phase ends with a working React slice.

**P0: Skeleton, CI, config** (Tier 0)
Repo layout, `config.py` with fail-closed validation, `clock.py`, DB engine (WAL, `BEGIN IMMEDIATE`), models, `/health`, `gen_keys.py`, `run_dev.ps1`, GitHub Actions (ruff, black, bandit, pip-audit, pytest).
*Done when:* app starts only with valid secrets and refuses placeholders; CI is green on an empty-ish test; tables are created.

**P1: Crypto core** (Tier 0)
`canonical.py`, `keys.py`, `crypto.py` (sign/verify, AES-GCM, envelope, KEK rotation), hypothesis property tests.
*Done when:* all Section 7.5 tests pass.

**P2: Audit log** (Tier 0)
`audit.py` (HMAC chain, checkpoints, anchor file, verify), `tamper_audit_demo.py` with three modes.
*Done when:* chain passes normally; `edit`, `recompute` and `truncate` each fail correctly with the right `first_bad_seq` / `truncated` flag.

**P3: Auth, RBAC, accounts** (Tier 0)
Register/login/logout, activation flow, pharmacist approval, JWT with `token_version`, lockout, `require_role`, object-level helpers, auto-generated RBAC matrix test, cookie + CSRF session. React login/register/activate pages.
*Done when:* the role x endpoint matrix passes; lockout after 5 failures; deactivated users' tokens stop working immediately; the admin never sees a doctor password.

**P4: Issue prescription** (Tier 0)
Payload v2, signing, QR, `pdf_layout.py` + PDF, envelope encryption of payload and PDF, `GET pdf`, key rotation. React "New Prescription" (with live preview) and "My Prescriptions".
*Done when:* issuing returns a valid `rx_id`; files on disk and `payload_enc` are ciphertext; owner downloads and decrypts; others get 404; wrong signing password gives generic 403 and lockout after 5.

**P5: Verify (QR) and dispense** (Tier 0)
`parse_qr`, steps 2-7 and 9-11, `/verify/qr`, `/dispense` with re-verification, fills, `dispenses` uniqueness, expiry, revoke, security alerts for replay. React Verify page (live scan/paste) with the verification-theatre timeline and seal.
*Done when:* tests cover VALID, TAMPERED (hash, signature, DB column), NOT_FOUND, INVALID_QR, EXPIRED (using the frozen clock), ALREADY_USED, REVOKED, refills; **concurrent dispense with 20 threads gives exactly one success per fill**; QR parser fuzz tests pass.
**Milestone M1 (end of week ~3): Tier 0 crypto demo works end to end in the browser.**

**P6: Rules-based risk (drug + dose)** (Tier 0)
`drug_match.py`, datasets, `risk.py` (rules only, anomaly term = 0 with `MODEL_UNAVAILABLE` warning), wired into issue (override flow) and verify.
*Done when:* fake drug => `UNKNOWN_DRUG` and SUSPICIOUS; absurd dose => dose flags; typo => `POSSIBLE_TYPO`; short names never fuzzy-match; override reason required above threshold.

**P7: Upload verification: render-and-diff + OCR** (Tier 1)
Start with the **spike** (Section 11.2). Then `ocr.py`, `rectify.py`, `render_diff.py`, `extract.py`, `/verify/upload`, `make_demo_samples.py`, tamper overlay in the UI.
*Done when (measured on the generated sample set of >= 20 genuine and >= 20 tampered files, including 5 slightly rotated/photographed):* genuine digital PDFs/images => VALID in 100%; genuine photos => VALID or REVIEW_REQUIRED (never TAMPERED) in >= 95%; single-digit dose edits => TAMPERED in >= 95% of digital cases with the correct zone outlined; white-box overlay and extra-medicine attacks => TAMPERED. Report the confusion matrix in `docs/evaluation.md`.

**P8: Anomaly model and evaluation** (Tier 1)
`features.py`, `generate_synthetic_data.py`, `train_anomaly.py`, `anomaly.py`, `model_io.py` (signed model), risk integration, explanations.
*Done when:* training prints and saves metrics (ROC-AUC, PR-AUC, P/R/F1, ablation, model comparison) with figures; missing or unsigned model => rules-only with `MODEL_UNAVAILABLE`, no crash; swapped model file is rejected.

**P9: Hardening and patient consent** (Tier 1)
Rate limiting with real client IP, upload validation, security headers, all alert rules, security events endpoint, patient PIN (`pin.py`), auditor role, `rotate_master_key.py`, interaction rules, bandit/pip-audit clean.
*Done when:* 6th rapid login gets 429; 5 failed verifications create a HIGH event; oversized/non-image upload rejected; PIN-less dispense of a PIN-protected prescription fails; KEK rotation keeps all PDFs readable; `bandit` has no high findings.

**P10: Frontend completion and attack suite** (Tier 0 + Tier 1)
Remaining pages, risk gauge, result components, admin and audit pages, `attack_suite.py` with all 16 attacks.
*Done when:* the full demo script (Section 18) runs end to end in the browser, and the attack suite reports every attack as detected/blocked.

**P11: Polish, docs, stretch** (Tier 0 docs; Tier 2 stretch)
README, `docs/` (architecture with Mermaid diagrams, crypto_spec, threat_model, evaluation, api, assumptions, demo_script), seed script, tidy code, deck, screen-recorded backup of the demo. Stretch items only if everything above is green.
*Done when:* a fresh clone follows the README and reaches a working demo in under 10 minutes on Windows.

---

## 16. Schedule and Team

**Deadline: Saturday 31 Oct 2026. Start: Sunday 18 Oct 2026. That is 13 days, team of 4.** The plan is therefore compressed: the four members work in **parallel tracks** from day 1 (AI modules, frontend and crypto are independent pure functions or API clients), and the cut line in Section 2 is applied as follows.

**Cuts for the 13-day window (decided):**
- **Dropped:** all Tier 2 items, interaction rules (11.4), pediatric rules, Docker, live browser scanner, offline QR, `bench.py`, `docs/api.md` (use the auto OpenAPI page instead).
- **Reduced:** the attack suite covers 10 attacks (#1, 3, 6, 8, 9, 10, 11, 13, 14, 15); model comparison is limited to Isolation Forest vs. LOF; `docs/` is limited to `architecture.md` (one Mermaid diagram of components and one of the verify flow), `threat_model.md`, `evaluation.md`, `assumptions.md`.
- **Protected:** everything in Tier 0, the patient PIN, HMAC audit chain with checkpoints, activation flow, auditor role, KEK rotation script (small), bandit/pip-audit in CI.
- **Render-and-diff is time-boxed:** the spike must reach a go/no-go by end of **Sat 24 Oct**. No-go => OCR-only comparison for digital renders (document this in `evaluation.md`).

| Date | Goal | Gate |
|---|---|---|
| Sun 18 - Mon 19 | P0, P1 (Member 1 + 2). In parallel: Member 3 builds datasets, `drug_match`, `risk` rules and starts the synthetic data generator; Member 4 scaffolds the React app, design tokens, shadcn components, fonts, app shell and login/dashboard pages against the API contract in Section 12 (typed client generated from `openapi.json`; fixtures until endpoints exist) | Crypto tests green; app refuses bad config; CI green |
| Tue 20 | P2 audit log, start P3 | Three audit tamper demos pass |
| Wed 21 | P3 auth/RBAC/activation | RBAC matrix green; login/register/activate pages work |
| Thu 22 | P4 issue + PDF + encryption | Issue and download in the browser |
| Fri 23 | P5 verify QR + dispense | **M1: issue -> verify -> dispense works end to end in the browser** |
| Sat 24 | P6 wired into issue/verify; P7 spike go/no-go | Rules risk live; spike decision recorded |
| Sun 25 | P7 upload verification; P8 model training + evaluation (Member 3) | Demo samples pass acceptance rates |
| Mon 26 | P9 hardening, PIN, KEK rotation; P8 integration | PIN + rate limits + alerts working |
| Tue 27 | P10 remaining pages + attack suite | **FEATURE FREEZE at end of day.** Only bug fixes after this. |
| Wed 28 | P11 docs, README, clean-machine install test | Fresh clone reaches a working demo in < 10 min |
| Thu 29 | Deck complete, rehearsal 1 | Full demo run without errors |
| Fri 30 | Rehearsal 2, record backup demo video, buffer for fixes | Video saved; submission package prepared |
| Sat 31 | **Submission day** | Do not start new work; submit and present |

If a gate is missed by more than half a day, cut the next-lowest item from Section 2 immediately instead of compressing testing or rehearsal time.

### 4-person ownership
| Member | Owns |
|---|---|
| 1 (Crypto) | `app/core/{canonical,crypto,keys,qr,pdf,pdf_layout,pin}.py`, `docs/crypto_spec.md`, crypto + QR tests, KEK rotation |
| 2 (Backend/Security) | skeleton, config, auth, RBAC, activation, routers, `audit.py`, `events.py`, rate limiting, CI, `threat_model.md`, `attack_suite.py` |
| 3 (AI) | `app/ai/*`, datasets, training + evaluation, rectify/render-diff, OCR, `evaluation.md`, model signing |
| 4 (Frontend/Integration) | React app (Section 13: design system, shell, Login/NewRx/MyRx pages, Playwright e2e), `make_demo_samples.py`, seed script, verification-service integration tests, README, deck, demo rehearsals |

### 3-person ownership
Merge Member 4 into the others: Member 1 also takes `make_demo_samples.py` and seed script; Member 2 also takes the React admin/audit pages and the README; Member 3 also takes the React Verify page (Seal, VerificationTimeline, TamperOverlay, RiskGauge components) because it renders AI output. In the 4-person split, Member 3 also builds `TamperOverlay` and `RiskGauge`. Drop Tier 2 entirely.

Everyone commits to the shared repo from the first week; the history should show all members.

---

## 17. Testing and Quality Gates

- **Coverage:** `pytest --cov` >= 85% on `app/core/` and `app/services/`; >= 70% overall.
- **Property tests (hypothesis):** canonical JSON is stable under key reordering and round-trips; `parse_qr` never crashes on arbitrary input and accepts only well-formed strings.
- **RBAC matrix:** every route x every role (+ anonymous) has an expected status code.
- **Concurrency:** dispense with 20 threads (SQLite WAL + `busy_timeout`) yields exactly `max_fills` successes.
- **Time:** all expiry/lockout/PIN tests use the frozen clock fixture; no `sleep`.
- **Isolation:** tests use a temporary SQLite DB and fixed test keys via `conftest.py`; never the real database.
- **Static analysis in CI:** `ruff`, `black --check`, `bandit -r app`, `pip-audit`.
- **Non-functional targets** (laptop CPU, no GPU): QR verify p95 < 150 ms; issue (excluding the intended PBKDF2 delay) p95 < 500 ms; upload verification < 8 s per page; app cold start < 10 s. Measure with a small `scripts/bench.py` and put the numbers in the deck.
- **Attack suite** (Section 14.3) must be 100% detected before feature freeze.

---

## 18. Demo Script (also the end-to-end test)

Run `python scripts/seed_demo.py` first (creates activated doctors, approved pharmacists, patients, auditor, plus an expired and a revoked sample).

1. **Genuine:** Doctor issues a prescription (with PIN-protected patient). Pharmacist scans it => **VALID**; the patient shows the PIN; dispense succeeds.
2. **Edited image:** Change one dose digit in the PDF image and upload => **TAMPERED** (`CONTENT_MISMATCH`), the altered cell outlined: "Signed 500 mg / Document reads 800 mg".
3. **Sneaky edits:** White-box overlay on a PDF => TAMPERED (`HIDDEN_TEXT_OR_OVERLAY`); an extra medicine line => TAMPERED.
4. **Forged QR:** Change one character of the QR text => **TAMPERED** (`INVALID_SIGNATURE` / `QR_HASH_MISMATCH`).
5. **Replay:** Pharmacist A dispenses; pharmacist B scans the same QR => **ALREADY_USED** + MEDIUM alert. A photographed copy without the PIN cannot be dispensed.
6. **Suspicious:** Doctor tries a fake drug or absurd dose => warning and override-reason prompt at issue; verification shows **SUSPICIOUS** with explanations. Show the anomaly flag for a 3 AM controlled-drug burst.
7. **Expired / revoked:** show the seeded samples.
8. **Audit log:** Auditor runs "Verify chain" => pass. Run `tamper_audit_demo.py --mode edit` => fail at the altered entry; `--mode recompute` => still fail; `--mode truncate` => truncation detected.
9. **Encrypted storage and key rotation:** show unreadable ciphertext in `storage/`; run `rotate_master_key.py`; PDFs still download.
10. **Attack suite:** run `attack_suite.py`; show the results table on the final slide.

---

## 19. Deliverables

**Code repository:** README (setup on Windows, `.env` generation, seeding, run, demo, disclaimer), clear commit history from all members, tests passing, CI badge, `.env.example`, no secrets committed.

**Presentation deck (~13 slides):**
1. Title and team
2. Problem: forged, edited, stolen and reused prescriptions
3. Idea in four lines + the three-adversary table (Section 1.1)
4. Architecture diagram (roles, backend, DB, storage, AI)
5. Cryptography: signing + WYSIWYS, envelope encryption, key lifecycle
6. Information security: RBAC, activation, replay protection, patient PIN, audit log
7. AI I: render-and-diff tamper localisation (before/after screenshot)
8. AI II: drug validation, anomaly detection, metrics and ablation (with honesty about synthetic data)
9. Verification decision flow (Section 10.2 as a flowchart)
10. STRIDE + attack suite results table
11. Live demo (Section 18)
12. Limitations, trust assumptions, and future work (Section 22)
13. Team contributions and Q&A (prepare answers: why not blockchain, why ECDSA, why server-side signing; see Section 24)

---

## 20. Coding Conventions

- Python 3.11+, type hints on all public functions, docstrings explaining the security reason for each decision.
- Format with `black` (line length 100) and lint with `ruff`.
- Pydantic v2 models for all request/response bodies.
- All datetimes are timezone-aware UTC and come from `clock.now_utc()`.
- Keep functions small and pure where possible (crypto and AI code must not touch the DB directly).
- Each module has a short top-of-file comment: purpose, inputs, outputs.
- No `print` of sensitive values; use `logging` with a redaction filter.
- Commit messages: `phase-N: short description`.

---

## 21. Definition of Done

- [ ] All Tier 0 acceptance criteria met; Tier 1 items either met or explicitly cut and documented
- [ ] `pytest` green with coverage targets; CI green including bandit and pip-audit
- [ ] Demo script (Section 18) works end to end from a fresh clone on Windows
- [ ] Attack suite: every attack detected/blocked
- [ ] No plaintext keys, passwords, PINs or secrets in code, logs, DB, or git history
- [ ] Every sensitive action appears in the audit log and the chain verifies, including checkpoints
- [ ] STRIDE threat model, architecture doc (with diagrams), crypto spec, evaluation doc, and assumptions doc written
- [ ] README has setup, `.env` generation, seeding, run commands, demo steps, and the "not for clinical use" disclaimer
- [ ] Deck ready, rehearsed twice, backup demo video recorded

---

## 22. Known Limitations and Future Work

State these honestly in the deck.

### 22.1 Limitations
- **Custodial signing:** the server decrypts the doctor's key in memory at signing time. A compromised server plus a phished signing password could forge signatures.
- Doses limited to mg; no liquids, injections, or compound units; no patient weight/renal adjustments.
- Image verification quality depends on photo quality; poor photos yield REVIEW_REQUIRED rather than a verdict.
- Drug, dose and interaction data are small demo datasets, not clinically validated.
- AI metrics come from synthetic data and show the method, not real-world accuracy.
- Local demo has no TLS, no HSM, SQLite is single-writer, account metadata is not encrypted.
- Rate-limit counters live in the memory of one server process (right for this demo; several workers would need a shared store).
- Dispensing re-checks the QR code, not the page. After a TAMPERED upload verdict the same pharmacist is blocked from dispensing that prescription for 30 minutes (`RX_DISPENSE_HELD`); a different pharmacist is not, because the signed record, not the paper, decides what is dispensed.
- Server-side verification is needed for one-time-use; the QR alone cannot prevent reuse offline.
- Not integrated with any hospital, pharmacy, or national health system.
- Indian regulatory references (Schedule H/H1/X, DPDP Act 2023, IT Act e-signatures, NMC registration) are illustrative and not legal advice.

### 22.2 Future work (Tier 2 stretch or beyond)
- **Offline-verifiable QR:** embed the zlib-compressed canonical payload plus signature and `key_id` in the QR (a few hundred bytes, well within QR capacity), cache a signed doctor key registry, and verify authenticity and content offline; reuse detection still needs the server. Run a feasibility spike on scan reliability first.
- **Non-custodial signing:** WebCrypto/WebAuthn in the browser so the private key never reaches the server.
- Live browser QR scanner; pediatric dose rules; multi-clinic key registry with transparency log; HSM/KMS for KEK and audit keys; TLS/mTLS; integration with real e-prescription standards.

---

## 23. Risk Register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Rectification/diff too unreliable on photos | Medium | Medium | Spike first (P7); digital-only guarantees; REVIEW_REQUIRED fallback; OCR-only fallback documented |
| Windows install problems with CV/ONNX packages | Medium | High | Pin versions in `requirements.lock` at P0; test fresh install weekly; RapidOCR instead of PyTorch OCR |
| SQLite lock contention in the concurrency test | Medium | Medium | WAL, `busy_timeout`, short transactions, `BEGIN IMMEDIATE` |
| Scope creep from Tier 1/2 | High | High | Cut line in Section 2; feature freeze week 7 |
| Demo fails live | Medium | High | Seeded deterministic data, frozen clock option, backup video, two rehearsals |
| One member's modules block others | Medium | Medium | Interfaces fixed in this spec; vertical slices; code review on every merge |
| Secrets committed by accident | Low | High | `.gitignore`, secret scan in CI, pre-commit check |
| Data/metric credibility questioned | Medium | Medium | Unseen-family test, ablation, explicit "synthetic" wording |

---

## 24. Decisions Considered and Rejected

| Idea | Why not |
|---|---|
| **Blockchain** for audit/anchoring | There is no multi-party trust problem to solve; an HMAC-chained log with signed, externally anchored checkpoints gives the same tamper evidence with far less complexity |
| **RSA instead of ECDSA** | Larger keys/signatures make the QR denser and harder to scan; P-256 is standard and fast. Ed25519 would also work; P-256 chosen for course alignment |
| **LLM-generated risk explanations** | Adds a heavy dependency and non-determinism; templated explanations from rule hits and feature percentiles are testable |
| **SQLCipher / full-DB encryption** | Hard to install on Windows; field-level envelope encryption covers the sensitive data and teaches the concept |
| **Client-side (non-custodial) signing now** | Hard to do reliably (key storage, recovery, multi-device) within the timeline; documented as future work with honest trust statement |
| **Hard-blocking high-risk prescriptions** | Blocks legitimate unusual care; override-with-reason plus alerting is more realistic |
| **EasyOCR as default** | Pulls in PyTorch and downloads models, which threatens the offline 10-minute setup goal |
| **Streamlit frontend** | Limited visual control, no live camera scanner, cannot reach the premium look required; replaced by React + Tailwind + shadcn/ui |
| **Next.js (SSR) instead of a Vite SPA** | A second server runtime and SSR add nothing here; the SPA is served by FastAPI on one origin, which simplifies cookies, CSRF and CSP |

---

## 25. Claude Code Tooling for This Project

**Skills to use (already available):**
- `impeccable`: design, critique, polish and harden the React UI against Section 13.1 (typography, spacing, colour, motion, accessibility, responsive behaviour). Used for the design-system setup on day 1 and a polish pass before freeze.
- `chrome-browser` (Claude in Chrome) or `built-in-browser`: open the running app, click through the demo flows, take screenshots for the deck, and check the console.
- `run`: launch the API + frontend and confirm a change works in the real app.
- `code-review` and `security-review`: run at the end of P1, P3, P5 and before freeze (crypto, auth and dispense code get the strictest review).
- `simplify`: cleanup pass after each phase.
- `init` / `update-config` / `fewer-permission-prompts`: keep `CLAUDE.md` short, add allow-rules for `pytest`, `ruff`, `npm run`, so sessions are not interrupted.
- `anthropic-skills:pptx` (or the slides artifact) for the deck, and `pdf` for checking generated prescription PDFs.

**MCP servers / connectors:**
- Already connected and useful: **Excalidraw** (architecture and flow diagrams for the deck and `docs/architecture.md`).
- Not needed: Google Drive/Docs/Sheets, DataRobot, database connectors. Do not enable them for this repo.
- Optional, recommended if the team wants them: a **Playwright MCP** (or just use the Playwright test runner already in `frontend/e2e`), and a **library-docs MCP** such as Context7 to fetch current Tailwind v4 / shadcn / TanStack Query docs and avoid outdated snippets. The project must still build without them.

**Plugins / hooks:** none required. Optionally add a pre-commit hook (via `update-config`) that runs `ruff`, `black --check` and a secret scan so keys are never committed.

**Environment verified (18 Oct 2026):** Python 3.11.9 (venv: `py -3.11 -m venv .venv`; do not use the default 3.14), Node 24, git 2.51.
