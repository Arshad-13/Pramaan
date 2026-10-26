# Pramaan: Phase Checklist

Companion to `Pramaan_SPEC.md` (the single source of truth). Section numbers below refer to the spec.
**Deadline: Sat 31 Oct 2026. Start: Sun 18 Oct 2026. Feature freeze: end of Tue 27 Oct.**
Tick a box only when its acceptance criterion is demonstrably met. Run `pytest -q` at the end of every phase. Commit format: `phase-N: short description`.

Owners: **M1** Crypto, **M2** Backend/Security, **M3** AI, **M4** Frontend/Integration.
Tiers: **T0** must ship, **T1** should ship, **T2** dropped for the 13-day window.

---

## P0: Skeleton, CI, config (Sun 18 - Mon 19) T0
- [x] Repo layout from Section 5 created; `py -3.11 -m venv .venv` works (M2)
- [x] `requirements.txt`, `requirements-dev.txt`, `.env.example`, `.gitignore` committed (M2)
- [x] `config.py` refuses to start with missing/placeholder `SECRET_KEY`, `MASTER_KEY`, `AUDIT_KEY` or missing audit signing key (M2)
- [x] `scripts/gen_keys.py` writes `.env` and `secrets/` (git-ignored) (M2)
- [x] `core/clock.py` with `FROZEN_TIME` support; no `datetime.now()` anywhere else (M2)
- [x] DB engine: SQLite WAL, `busy_timeout`, `BEGIN IMMEDIATE` on writes; all models from Section 6 create tables (M2)
- [x] `GET /api/health` returns 200 (M2)
- [x] GitHub Actions: ruff, black --check, bandit, pip-audit, pytest (M2) (first run green on 82e3b87)
- [x] Vite + React + TS app scaffolded; Tailwind v4, shadcn-style components (Radix + cva, owned in `src/components/ui`), fonts, design tokens (Section 13.1), app shell (M4)
- [x] `requirements.lock` pinned from a clean venv (M2)

**Done when:** app starts only with valid secrets; CI green; frontend shell renders in light and dark.

## P1: Crypto core (Sun 18 - Mon 19) T0
- [x] `canonical.py`: NFC normalisation, control/bidi rejection, canonical bytes, SHA-256 (M1)
- [x] `crypto.py`: ECDSA P-256 sign/verify with `PRAMAAN-RX-v2` context, raw 64-byte signatures (M1)
- [x] `keys.py`: keypair, `key_id`, PBKDF2 + AES-GCM private-key protection, wrong-password failure (M1)
- [x] Envelope encryption: DEK per prescription, AAD binding, KEK wrap with `kek_version` (M1)
- [x] `pin.py`: HMAC-based 6-digit PIN with time step (M1)
- [x] Tests (Section 7.5): round trip, bit flip, wrong key, wrong context, wrong password, GCM tamper, swapped AAD, canonical stability, hypothesis properties (M1)

**Done when:** all crypto tests green.

## P2: Audit log (Tue 20) T0
- [x] `audit.py`: HMAC chain, appends in the caller's transaction, no commit inside (M2)
- [x] Signed checkpoints every 50 entries + on demand; `ANCHOR_FILE` lines appended (M2)
- [x] `verify_chain` returns `ok`, `checked`, `first_bad_seq`, `checkpoint_ok`, `truncated` (M2)
- [x] `scripts/tamper_audit_demo.py` with `edit`, `recompute`, `truncate` modes (M2)
- [x] `tests/test_audit_chain.py` covers all three tamper modes (M2)

**Done when:** chain passes normally; each tamper mode fails with the right result.

## P3: Auth, RBAC, accounts (Tue 20 - Wed 21) T0
- [x] Register (patient, pharmacist=PENDING), login, logout, `/auth/me`, change password (M2)
- [x] argon2id, min length 10, dummy-hash timing equalisation, generic 401 for unknown/locked (M2)
- [x] JWT loaded against DB on every request; `token_version` revocation; explicit `algorithms=["HS256"]` (M2)
- [x] HttpOnly cookie session + CSRF double-submit; Bearer still accepted for scripts (M2)
- [x] Lockout after `MAX_FAILED_LOGINS` (M2)
- [x] Admin creates doctor, one-time activation token (hash stored, 24 h); `/auth/activate` sets login + signing passwords and generates key (M2, M1)
- [x] Pharmacist approve/reject; deactivate = suspend (revokes keys) (M2)
- [x] Auditor role (the object-level 404 helper arrives with prescriptions in P4) (M2)
- [x] Auto-generated role x endpoint RBAC matrix test (M2)
- [x] React: login, register, activate pages (M4)

**Done when:** RBAC matrix green; lockout after 5 failures; deactivated user's token fails at once; admin never sees a doctor password.

Extras done in P3: audit endpoints (`/admin/audit`, `verify`, `checkpoint`), `scripts/create_user.py` to bootstrap admin/auditor, admin UI (approvals, activation-code panel, user list, deactivate). Admin accounts use public UUIDs in URLs (`/admin/users/{user_id}`).

## P4: Issue prescription (Wed 21 - Thu 22) T0
- [x] Payload v2 built once; `max_fills`, doctor/patient blocks, `key_id` (M1)
- [x] `pdf_layout.py` (single source of positions, fiducials) + deterministic `pdf.py` from payload only (M1)
- [x] QR `PRM2...` build/parse with strict validation; fuzz tests (M1)
- [x] `POST /prescriptions`: sign, encrypt payload + PDF, store, audit in same transaction (M2)
- [x] Wrong signing password: generic 403; lockout after `MAX_FAILED_UNLOCKS` (M2)
- [x] `GET /prescriptions/{id}/pdf` (owner only), `/prescriptions/mine`, revoke, exact patient lookup (M2)
- [x] `POST /keys/rotate`, `GET /keys/mine` (M2)
- [x] React: New Prescription with live preview; My Prescriptions (M4)

**Done when:** files on disk and `payload_enc` are ciphertext; owner can download; others get 404.

## P5: Verify (QR) and dispense (Thu 22 - Fri 23) T0
- [x] `verification_service` steps 2-7 and 9-11 (Section 10.2), response schema (10.4) (M2)
- [x] Signed-payload cross-checks (expiry, doctor, patient, `max_fills`) (M2)
- [x] `/verify/qr`; `verification_attempts` and audit entries (M2)
- [x] `/dispense` re-verifies inside one transaction; atomic fill update; `dispenses` `UNIQUE(rx_id, fill_no)` (M2)
- [x] Revoke vs dispense race handled by conditional UPDATE (M2)
- [x] Replay alert: other pharmacist verifies a DISPENSED rx (M2)
- [x] Tests: VALID, TAMPERED (hash, signature, DB column), NOT_FOUND, INVALID_QR, EXPIRED (frozen clock), ALREADY_USED, REVOKED, refills (M2)
- [x] Concurrency test: 20 threads give exactly one success per fill (M2)
- [x] React: Verify page with live camera scan, paste, verification timeline, seal, verified-record card (M4, M3)

**Done when:** all of the above pass. **M1 milestone (Fri 23): issue -> verify -> dispense works end to end in the browser.**

Built early in P5 because every prescription requires a patient PIN by default: `GET /prescriptions/{id}/pin`, PIN check and 3-wrong-PIN lock at dispense, patient PIN ring, PIN field on the dispense panel, and the POSSIBLE_REPLAY and FAILED_VERIFICATIONS alerts (so P9 only has the remaining alert rules). Verification is read-only; only dispense consumes a fill.

## P6: Rules-based risk (Sat 24) T0
- [x] `data/drugs.csv` (>= 100 names incl. Indian brands) and `drug_reference.csv` (>= 40 rows) (M3)
- [x] `drug_match.py`: exact first, length-guarded fuzzy, `UNKNOWN_DRUG` / `POSSIBLE_TYPO` (M3)
- [x] `dose_check`: single max, daily max, controlled schedule (M3)
- [x] `risk.py` rules-only, `MODEL_UNAVAILABLE` warning when no model (M3)
- [x] Issue flow: warning + required override reason; `RX_ISSUED_WITH_OVERRIDE` audit; no hard block (M2, M3)
- [x] Verify flow: stored issue-time score + new signals; SUSPICIOUS at threshold (M2, M3)
- [x] React: risk panel with explanations and override box (M4)

**Done when:** fake drug => SUSPICIOUS; absurd dose => dose flags; short names never fuzzy-match.

Also built: live `POST /prescriptions/risk-check` (typo hints, score, whether a reason is needed), `GET /drugs` for autosuggest, a RISK_OVERRIDE LOW security event for admins, and controlled medicines are limited to one fill. Not in this phase: drug-interaction rules (cut for the 13-day window), the anomaly term (Phase 8).

## P7: Upload verification, render-and-diff (Sat 24 spike, Sun 25 build) T1
- [x] **Spike go/no-go recorded** (GO, done early) (rectify + diff on 10 sample photos); no-go => OCR-only fallback (M3)
- [x] `ocr.py` RapidOCR adapter; `rectify.py`; `render_diff.py`; `extract.py` (M3)
- [x] QR decode from image/PDF with fallbacks (M3)
- [x] Text-layer vs rendered-page check (`HIDDEN_TEXT_OR_OVERLAY`) (M3)
- [x] Extra-content detection in unused rows/margins (M3)
- [x] `/verify/upload` with magic-byte and size checks; `REVIEW_REQUIRED` result (M2, M3)
- [x] `evaluate_upload.py` (replaces `make_demo_samples.py`; writes the samples to `samples/`): >= 20 genuine + >= 20 tampered (5 photographed) (M4)
- [x] React: upload drop zone, `TamperOverlay` with signed-vs-read callouts (M3)
- [x] Results table in `docs/evaluation.md` (M3)

**Done when:** genuine digital => VALID 100%; genuine photos never TAMPERED (>= 95% VALID/REVIEW); single-digit edits => TAMPERED >= 95% with correct zone; overlay and extra-medicine attacks => TAMPERED.

## P8: Anomaly model and evaluation (Sun 25 - Mon 26) T1
- [x] `features.py` (10 features incl. per-doctor baselines) shared by training and inference (M3)
- [x] `generate_synthetic_data.py`: normals + tuning anomaly families + unseen test family (M3)
- [x] `train_anomaly.py`: Isolation Forest; ROC-AUC, PR-AUC, P/R/F1, ablation, IF vs LOF; figures (M3)
- [x] Percentile-normalised score; per-feature explanations (M3)
- [x] `model_io.py`: signed model file, verify before `joblib.load` (M3, M1); run `python scripts/train_anomaly.py` after `gen_keys.py` to create it
- [x] Missing/unsigned model => rules-only + warning + HIGH event, no crash (M3)
- [x] `docs/evaluation.md` states clearly that data is synthetic (M3)

**Done when:** metrics and figures generated; swapped model file rejected.

## P9: Hardening and patient consent (Mon 26) T1
- [x] Rate limits (own sliding-window limiter, `slowapi` dropped): login 5/min per IP and account; verify 30/min per user (M2)
- [x] Upload validation, security headers, strict CSP, docs off unless `DEBUG` (M2)
- [x] All alert rules from Section 8.4 and `/admin/security-events` (M2)
- [x] Patient PIN: `/prescriptions/{id}/pin`, dispense requires PIN, 3-try lock (M1, M2) (done in P5)
- [x] `scripts/rotate_master_key.py` re-wraps DEKs; PDFs still readable (M1)
- [x] bandit clean of high findings; pip-audit clean (M2)
- [x] React: PIN ring for patients, PIN field on dispense (M4) (done in P5)

**Done when:** 6th rapid login gets 429; 5 failed verifications create a HIGH event; PIN-less dispense of protected rx fails; KEK rotation keeps PDFs readable.

## P10: Frontend completion and attack suite (Mon 26 - Tue 27) T0 + T1
- [x] Dashboard, Admin (approvals, activation-token dialog, key revoke, events), Audit (chain view, verify, checkpoint) pages (M4)
- [x] `RiskGauge`, `AuditChain`, `PinRing` components; reduced-motion support (M4, M3)
- [x] `impeccable` polish pass: contrast, focus, spacing, responsive phone-width Verify (M4) (axe WCAG A/AA clean in light and dark, phone width checked; no further visual pass)
- [x] `scripts/attack_suite.py`: attacks #1, 3, 6, 8, 9, 10, 11, 13, 14, 15; results table (M2)
- [x] Playwright e2e for the demo script; screenshots saved for the deck (M4)
- [x] `seed_demo.py` creates activated doctors, approved pharmacists, patients, auditor, expired + revoked samples (M4)
- [ ] `code-review` and `security-review` run on crypto, auth, dispense code; findings fixed (all) (only a manual grep-level review so far)

**Done when:** full demo (Section 18) runs in the browser; attack suite reports every attack detected/blocked. **FEATURE FREEZE at end of Tue 27.**

## P11: Docs, deck, rehearsal (Wed 28 - Fri 30) T0
- [x] `README.md`: Windows setup, `.env` generation, seed, run, demo steps, disclaimer (M4)
- [x] `docs/architecture.md` (Mermaid: components + verify flow), `threat_model.md`, `evaluation.md`, `assumptions.md` (all)
- [x] Fresh-clone install test: clone, install, keys, model, seed, attack suite 16/16 and serving the app all worked from a clean checkout (M4)
- [x] Deck (13 slides, `docs/Pramaan_deck.pptx`) with attack-suite and evaluation slides; add team names (all)
- [ ] Rehearsal 1 (Thu 29) and rehearsal 2 (Fri 30); backup demo video recorded (all)
- [x] Prepared answers: why not blockchain, why ECDSA, why server-side signing (last slide and Section 24) (all)
- [ ] Submission package prepared (Fri 30); no new work on Sat 31 (all)

---

## Improvement pass (Mon 26 - Tue 27 Oct)
Audit and plan in [`docs/IMPROVEMENT_PLAN.md`](docs/IMPROVEMENT_PLAN.md).
- [x] I1 verdict clarity, I2 sessions and account page, I3 frontend resilience, I4 backend operability, I5 first-load size
- [x] I6 proof: full gate green, 128 frontend tests, e2e 6/6 with axe, attack suite 16/16, real dev database upgrades cleanly

---

## Final Definition of Done (Section 21)
- [ ] All T0 acceptance criteria met; T1 items met or explicitly cut and documented
- [ ] `pytest` green, coverage >= 85% on `app/core` and `app/services` (measured Tue 27 Oct: 97.2% and 96.0%); CI green (check the Actions tab)
- [ ] Demo works from a fresh clone on Windows
- [ ] Attack suite: every attack detected or blocked
- [ ] No plaintext keys, passwords, PINs or secrets in code, logs, DB or git history
- [ ] Every sensitive action is audited and the chain verifies, including checkpoints
- [ ] Docs, README and disclaimer in place; deck rehearsed twice with backup video
