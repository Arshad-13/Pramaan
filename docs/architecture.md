# Architecture

Pramaan is one FastAPI process plus a React app that it serves. State lives in SQLite and an encrypted `storage/` folder. Nothing else is needed to run it.

## Components

```mermaid
flowchart LR
  subgraph Browser
    UI["React app<br/>doctor / patient / pharmacist / admin / auditor"]
  end
  subgraph API["FastAPI (one process)"]
    MW["Security headers, CORS, rate limits"]
    R["Routers + role checks (require_role)"]
    S["Services<br/>accounts, keys, prescriptions, verification, events, rotation"]
    AI["AI module<br/>drug match, risk rules, anomaly model,<br/>render-and-diff, OCR"]
    C["Crypto core<br/>canonical JSON, ECDSA P-256, AES-GCM,<br/>PIN, HMAC audit chain"]
  end
  DB[("SQLite<br/>users, keys, prescriptions (encrypted payload),<br/>dispenses, audit_log, events")]
  ST[("storage/<br/>encrypted PDFs, audit anchors")]
  KEYS[/"secrets/ and .env<br/>master key, audit key, audit signing key"/]
  MODEL[/"models/iforest.joblib + .sig"/]

  UI -->|"HTTPS-ready, cookie + CSRF"| MW --> R --> S
  S --> C
  S --> AI
  S --> DB
  S --> ST
  C --> KEYS
  AI -->|"signature checked before load"| MODEL
```

## Issuing

```mermaid
sequenceDiagram
  participant D as Doctor (browser)
  participant A as API
  participant K as Key store
  participant P as PDF + QR
  D->>A: medicines, patient, signing password
  A->>A: build payload v2, reject anything that cannot be printed faithfully
  A->>A: risk check (rules + anomaly model); override reason if high
  A->>K: unlock doctor's private key (password, lockout rules)
  A->>A: canonical JSON -> SHA-256 -> ECDSA signature
  A->>P: render PDF from the SAME payload; QR = id.key.hash.signature
  A->>A: encrypt payload + PDF under a fresh data key, wrap it with the master key
  A->>A: store everything and the audit entry in one transaction
  A-->>D: signed prescription (PDF download)
```

## Verification decision flow

```mermaid
flowchart TD
  start([QR text, or photo/PDF]) --> up{"upload?"}
  up -- yes --> find["find QR in the file"]
  find -->|none| inv[INVALID_QR]
  up -- no --> parse
  find --> parse["parse QR strictly"]
  parse -->|malformed| inv
  parse --> look["find prescription"]
  look -->|none| nf[NOT_FOUND]
  look --> dec["decrypt payload, recompute hash"]
  dec --> sig["check ECDSA signature + key"]
  sig --> cross["plain DB columns agree with signed payload?"]
  cross -->|"any check failed"| tam[TAMPERED]
  cross --> page{"upload?"}
  page -- yes --> diff["redraw expected page, straighten upload, compare field by field + OCR + PDF text layer"]
  diff -->|"fields differ / extra writing / hidden text"| tam
  diff -->|"cannot read an important field"| rev[REVIEW_REQUIRED]
  diff --> state
  page -- no --> state["doctor and key state, status, expiry"]
  state -->|revoked / suspended| rvk[REVOKED]
  state -->|all fills used| used[ALREADY_USED]
  state -->|past expiry| exp[EXPIRED]
  state --> risk["stored risk score + multi-pharmacy signal"]
  risk -->|"above threshold"| sus[SUSPICIOUS]
  risk --> ok[VALID]
```

Precedence when several apply: TAMPERED > REVOKED > ALREADY_USED > EXPIRED > SUSPICIOUS > REVIEW_REQUIRED > VALID. Verification never consumes a fill; only dispensing does, with the patient's PIN, in one atomic update.

## Where the security properties come from

| Property | Mechanism | Code |
|---|---|---|
| What you see is what was signed | The PDF is rendered from the signed payload; uploads are compared field by field with a redrawn copy | `core/payload.py`, `core/pdf.py`, `ai/content_check.py` |
| Authenticity | ECDSA P-256 per doctor, domain-separated, fixed-length signatures | `core/crypto.py`, `core/keys.py` |
| Confidentiality at rest | Per-prescription AES-256-GCM data key, wrapped by the master key | `core/crypto.py`, `services/rotation.py` |
| No double spend | One conditional UPDATE plus `UNIQUE(rx_id, fill_no)` | `services/verification_service.py` |
| Consent | Patient PIN derived from a per-prescription secret, 3-try lock | `core/pin.py` |
| Accountability | HMAC-chained audit log, signed checkpoints, external anchor file | `core/audit.py` |
| Model integrity | Model file signed; signature verified before it is unpickled | `ai/model_io.py` |
