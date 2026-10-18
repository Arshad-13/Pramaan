# Pramaan: Phase Checklist

Companion to `Pramaan_SPEC.md` (the single source of truth). Section numbers below refer to the spec.
**Deadline: Sat 31 Oct 2026. Start: Sun 18 Oct 2026. Feature freeze: end of Tue 27 Oct.**
Tick a box only when its acceptance criterion is demonstrably met. Run `pytest -q` at the end of every phase. Commit format: `phase-N: short description`.

Owners: **M1** Crypto, **M2** Backend/Security, **M3** AI, **M4** Frontend/Integration.
Tiers: **T0** must ship, **T1** should ship, **T2** dropped for the 13-day window.

---

## P0: Skeleton, CI, config (Sun 18 - Mon 19) T0
- [ ] Repo layout from Section 5 created; `py -3.12 -m venv .venv` works (M2)
- [ ] `requirements.txt`, `requirements-dev.txt`, `.env.example`, `.gitignore` committed (M2)
- [ ] `config.py` refuses to start with missing/placeholder `SECRET_KEY`, `MASTER_KEY`, `AUDIT_KEY` or missing audit signing key (M2)
- [ ] `scripts/gen_keys.py` writes `.env` and `secrets/` (git-ignored) (M2)
- [ ] `core/clock.py` with `FROZEN_TIME` support; no `datetime.now()` anywhere else (M2)
- [ ] DB engine: SQLite WAL, `busy_timeout`, `BEGIN IMMEDIATE` on writes; all models from Section 6 create tables (M2)
- [ ] `GET /api/health` returns 200 (M2)
- [ ] GitHub Actions: ruff, black --check, bandit, pip-audit, pytest (M2)
- [ ] Vite + React + TS app scaffolded; Tailwind v4, shadcn/ui, fonts, design tokens (Section 13.1), app shell (M4)
- [ ] `requirements.lock` pinned from a clean venv (M2)

**Done when:** app starts only with valid secrets; CI green; frontend shell renders in light and dark.

## P1: Crypto core (Sun 18 - Mon 19) T0
- [ ] `canonical.py`: NFC normalisation, control/bidi rejection, canonical bytes, SHA-256 (M1)
- [ ] `crypto.py`: ECDSA P-256 sign/verify with `PRAMAAN-RX-v2` context, raw 64-byte signatures (M1)
- [ ] `keys.py`: keypair, `key_id`, PBKDF2 + AES-GCM private-key protection, wrong-password failure (M1)
- [ ] Envelope encryption: DEK per prescription, AAD binding, KEK wrap with `kek_version` (M1)
- [ ] `pin.py`: HMAC-based 6-digit PIN with time step (M1)
- [ ] Tests (Section 7.5): round trip, bit flip, wrong key, wrong context, wrong password, GCM tamper, swapped AAD, canonical stability, hypothesis properties (M1)

**Done when:** all crypto tests green.

## P2: Audit log (Tue 20) T0
- [ ] `audit.py`: HMAC chain, appends in the caller's transaction, no commit inside (M2)
- [ ] Signed checkpoints every 50 entries + on demand; `ANCHOR_FILE` lines appended (M2)
- [ ] `verify_chain` returns `ok`, `checked`, `first_bad_seq`, `checkpoint_ok`, `truncated` (M2)
- [ ] `scripts/tamper_audit_demo.py` with `edit`, `recompute`, `truncate` modes (M2)
- [ ] `tests/test_audit_chain.py` covers all three tamper modes (M2)

**Done when:** chain passes normally; each tamper mode fails with the right result.

## P3: Auth, RBAC, accounts (Tue 20 - Wed 21) T0
- [ ] Register (patient, pharmacist=PENDING), login, logout, `/auth/me`, change password (M2)
- [ ] argon2id, min length 10, dummy-hash timing equalisation, generic 401 for unknown/locked (M2)
- [ ] JWT loaded against DB on every request; `token_version` revocation; explicit `algorithms=["HS256"]` (M2)
- [ ] HttpOnly cookie session + CSRF double-submit; Bearer still accepted for scripts (M2)
- [ ] Lockout after `MAX_FAILED_LOGINS` (M2)
- [ ] Admin creates doctor, one-time activation token (hash stored, 24 h); `/auth/activate` sets login + signing passwords and generates key (M2, M1)
- [ ] Pharmacist approve/reject; deactivate = suspend (revokes keys) (M2)
- [ ] Auditor role; object-level checks return 404 (M2)
- [ ] Auto-generated role x endpoint RBAC matrix test (M2)
- [ ] React: login, register, activate pages (M4)

**Done when:** RBAC matrix green; lockout after 5 failures; deactivated user's token fails at once; admin never sees a doctor password.

## P4: Issue prescription (Wed 21 - Thu 22) T0
- [ ] Payload v2 built once; `max_fills`, doctor/patient blocks, `key_id` (M1)
- [ ] `pdf_layout.py` (single source of positions, fiducials) + deterministic `pdf.py` from payload only (M1)
- [ ] QR `PRM2...` build/parse with strict validation; fuzz tests (M1)
- [ ] `POST /prescriptions`: sign, encrypt payload + PDF, store, audit in same transaction (M2)
- [ ] Wrong signing password: generic 403; lockout after `MAX_FAILED_UNLOCKS` (M2)
- [ ] `GET /prescriptions/{id}/pdf` (owner only), `/prescriptions/mine`, revoke, exact patient lookup (M2)
- [ ] `POST /keys/rotate`, `GET /keys/mine` (M2)
- [ ] React: New Prescription with live preview; My Prescriptions (M4)

**Done when:** files on disk and `payload_enc` are ciphertext; owner can download; others get 404.

## P5: Verify (QR) and dispense (Thu 22 - Fri 23) T0
- [ ] `verification_service` steps 2-7 and 9-11 (Section 10.2), response schema (10.4) (M2)
- [ ] Signed-payload cross-checks (expiry, doctor, patient, `max_fills`) (M2)
- [ ] `/verify/qr`; `verification_attempts` and audit entries (M2)
- [ ] `/dispense` re-verifies inside one transaction; atomic fill update; `dispenses` `UNIQUE(rx_id, fill_no)` (M2)
- [ ] Revoke vs dispense race handled by conditional UPDATE (M2)
- [ ] Replay alert: other pharmacist verifies a DISPENSED rx (M2)
- [ ] Tests: VALID, TAMPERED (hash, signature, DB column), NOT_FOUND, INVALID_QR, EXPIRED (frozen clock), ALREADY_USED, REVOKED, refills (M2)
- [ ] Concurrency test: 20 threads give exactly one success per fill (M2)
- [ ] React: Verify page with live camera scan, paste, verification timeline, seal, verified-record card (M4, M3)

**Done when:** all of the above pass. **M1 milestone (Fri 23): issue -> verify -> dispense works end to end in the browser.**

## P6: Rules-based risk (Sat 24) T0
- [ ] `data/drugs.csv` (>= 100 names incl. Indian brands) and `drug_reference.csv` (>= 40 rows) (M3)
- [ ] `drug_match.py`: exact first, length-guarded fuzzy, `UNKNOWN_DRUG` / `POSSIBLE_TYPO` (M3)
- [ ] `dose_check`: single max, daily max, controlled schedule (M3)
- [ ] `risk.py` rules-only, `MODEL_UNAVAILABLE` warning when no model (M3)
- [ ] Issue flow: warning + required override reason; `RX_ISSUED_WITH_OVERRIDE` audit; no hard block (M2, M3)
- [ ] Verify flow: stored issue-time score + new signals; SUSPICIOUS at threshold (M2, M3)
- [ ] React: risk panel with explanations and override box (M4)

**Done when:** fake drug => SUSPICIOUS; absurd dose => dose flags; short names never fuzzy-match.

## P7: Upload verification, render-and-diff (Sat 24 spike, Sun 25 build) T1
- [ ] **Spike go/no-go recorded by end of Sat 24** (rectify + diff on 10 sample photos); no-go => OCR-only fallback (M3)
- [ ] `ocr.py` RapidOCR adapter; `rectify.py`; `render_diff.py`; `extract.py` (M3)
- [ ] QR decode from image/PDF with fallbacks (M3)
- [ ] Text-layer vs rendered-page check (`HIDDEN_TEXT_OR_OVERLAY`) (M3)
- [ ] Extra-content detection in unused rows/margins (M3)
- [ ] `/verify/upload` with magic-byte and size checks; `REVIEW_REQUIRED` result (M2, M3)
- [ ] `make_demo_samples.py`: >= 20 genuine + >= 20 tampered (5 photographed) (M4)
- [ ] React: upload drop zone, `TamperOverlay` with signed-vs-read callouts (M3)
- [ ] Results table in `docs/evaluation.md` (M3)

**Done when:** genuine digital => VALID 100%; genuine photos never TAMPERED (>= 95% VALID/REVIEW); single-digit edits => TAMPERED >= 95% with correct zone; overlay and extra-medicine attacks => TAMPERED.

## P8: Anomaly model and evaluation (Sun 25 - Mon 26) T1
- [ ] `features.py` (10 features incl. per-doctor baselines) shared by training and inference (M3)
- [ ] `generate_synthetic_data.py`: normals + tuning anomaly families + unseen test family (M3)
- [ ] `train_anomaly.py`: Isolation Forest; ROC-AUC, PR-AUC, P/R/F1, ablation, IF vs LOF; figures (M3)
- [ ] Percentile-normalised score; per-feature explanations (M3)
- [ ] `model_io.py`: signed model file, verify before `joblib.load` (M3, M1)
- [ ] Missing/unsigned model => rules-only + warning + HIGH event, no crash (M3)
- [ ] `docs/evaluation.md` states clearly that data is synthetic (M3)

**Done when:** metrics and figures generated; swapped model file rejected.

## P9: Hardening and patient consent (Mon 26) T1
- [ ] slowapi limits: login 5/min per IP and account; verify 30/min per user (M2)
- [ ] Upload validation, security headers, strict CSP, docs off unless `DEBUG` (M2)
- [ ] All alert rules from Section 8.4 and `/admin/security-events` (M2)
- [ ] Patient PIN: `/prescriptions/{id}/pin`, dispense requires PIN, 3-try lock (M1, M2)
- [ ] `scripts/rotate_master_key.py` re-wraps DEKs; PDFs still readable (M1)
- [ ] bandit clean of high findings; pip-audit clean (M2)
- [ ] React: PIN ring for patients, PIN field on dispense (M4)

**Done when:** 6th rapid login gets 429; 5 failed verifications create a HIGH event; PIN-less dispense of protected rx fails; KEK rotation keeps PDFs readable.

## P10: Frontend completion and attack suite (Mon 26 - Tue 27) T0 + T1
- [ ] Dashboard, Admin (approvals, activation-token dialog, key revoke, events), Audit (chain view, verify, checkpoint) pages (M4)
- [ ] `RiskGauge`, `AuditChain`, `PinRing` components; reduced-motion support (M4, M3)
- [ ] `impeccable` polish pass: contrast, focus, spacing, responsive phone-width Verify (M4)
- [ ] `scripts/attack_suite.py`: attacks #1, 3, 6, 8, 9, 10, 11, 13, 14, 15; results table (M2)
- [ ] Playwright e2e for the demo script; screenshots saved for the deck (M4)
- [ ] `seed_demo.py` creates activated doctors, approved pharmacists, patients, auditor, expired + revoked samples (M4)
- [ ] `code-review` and `security-review` run on crypto, auth, dispense code; findings fixed (all)

**Done when:** full demo (Section 18) runs in the browser; attack suite reports every attack detected/blocked. **FEATURE FREEZE at end of Tue 27.**

## P11: Docs, deck, rehearsal (Wed 28 - Fri 30) T0
- [ ] `README.md`: Windows setup, `.env` generation, seed, run, demo steps, disclaimer (M4)
- [ ] `docs/architecture.md` (Mermaid: components + verify flow), `threat_model.md`, `evaluation.md`, `assumptions.md` (all)
- [ ] Fresh-clone install test on a clean machine: demo in < 10 min (M4)
- [ ] Deck (~13 slides, Section 19) with attack-suite and evaluation slides (all)
- [ ] Rehearsal 1 (Thu 29) and rehearsal 2 (Fri 30); backup demo video recorded (all)
- [ ] Prepared answers: why not blockchain, why ECDSA, why server-side signing (Section 24) (all)
- [ ] Submission package prepared (Fri 30); no new work on Sat 31 (all)

---

## Final Definition of Done (Section 21)
- [ ] All T0 acceptance criteria met; T1 items met or explicitly cut and documented
- [ ] `pytest` green, coverage >= 85% on `app/core` and `app/services`; CI green
- [ ] Demo works from a fresh clone on Windows
- [ ] Attack suite: every attack detected or blocked
- [ ] No plaintext keys, passwords, PINs or secrets in code, logs, DB or git history
- [ ] Every sensitive action is audited and the chain verifies, including checkpoints
- [ ] Docs, README and disclaimer in place; deck rehearsed twice with backup video
