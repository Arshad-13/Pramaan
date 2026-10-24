# Pramaan: Tamper-Proof Prescription Verifier

*Pramaan (प्रमाण) means "proof".* A doctor issues a digitally signed prescription with a QR code; a pharmacist scans it and learns whether it is genuine, tampered, expired, already used, revoked or suspicious. Course project for AI 331 Information Security and Cryptography, SVNIT Surat.

> **Academic demo. Not for clinical use.** Medical reference data in `data/` is approximate.

The full design is in [`Pramaan_SPEC.md`](Pramaan_SPEC.md); progress is tracked in [`PHASE_CHECKLIST.md`](PHASE_CHECKLIST.md).

## Quick start (Windows)

Requirements: Python 3.11 (not 3.14), Node 20.19+ or 22+, git.

```powershell
# 1. Backend
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe scripts\gen_keys.py          # writes .env + secrets/ (git-ignored)
.\.venv\Scripts\python.exe scripts\train_anomaly.py        # trains and signs the anomaly model (models/, git-ignored); without it the app runs on rules only

# 2. Frontend
cd frontend
npm install
cd ..

# 3. Create the demo world (accounts, history, sample files). WIPES the local database.
.\.venv\Scripts\python.exe scripts\seed_demo.py --reset --samples samples\demo

# 4. Run API (:8000) and Vite dev server (:5173) together
.\scripts\run_dev.ps1
```

Open <http://localhost:5173>. For a single-process build, run `npm run build` in `frontend/` and then `uvicorn app.main:app`; FastAPI serves the built app on <http://localhost:8000>.

The app **refuses to start** if `.env` is missing or contains placeholder or malformed secrets.

## Demo accounts and the demo script

`seed_demo.py` prints these (all local demo passwords). Doctors' signing password: `Doctor-Signing-Phrase-9`.

| Role | Email | Password |
|---|---|---|
| Admin | admin@pramaan.test | Admin-Demo-2026 |
| Auditor | auditor@pramaan.test | Auditor-Demo-2026 |
| Doctor | dr.shah@clinic.test, dr.iyer@clinic.test | Doctor-Login-2026 |
| Pharmacist | meera@citypharm.test, rohan@medplus.test | Pharma-Secret-2026 |
| Patient | ravi.patel@example.test (and sneha.rao, kabir.khan, anita.desai @example.test) | Patient-Demo-2026 |

Sample files are in `samples/demo/` (`ready.pdf`, forged variants, one `.qr.txt` per case). The demo script of the spec (Section 18) in short:

1. **Genuine:** as Dr. Shah, issue a prescription; as the pharmacist, upload its PDF on *Verify* -> Verified; the patient's PIN (patient account, *Show PIN*) lets you dispense.
2. **Edited image:** upload `ready_forged_dose_800mg.png` -> Tampered, with the dose cell outlined ("Signed 500 mg / Document reads 800 mg"). Also try the photo, `ready_forged_overlay.pdf`, `ready_forged_hidden_text.pdf`, `ready_forged_extra_medicine.png`.
3. **Forged code:** paste `ready_forged_qr.qr.txt` on the Paste tab -> Tampered.
4. **Replay:** dispense as Meera, then verify the same file as Rohan -> Already used, and a MEDIUM alert appears under *Administration*.
5. **Other states:** paste `expired`, `revoked`, `suspicious`, `used` and `controlled` codes.
6. **Audit log:** as the auditor, *Verify chain*. To show detection, run `python scripts/tamper_audit_demo.py --mode edit` (works on a copy).
7. **Encryption and key rotation:** `storage/*.pdf.enc` is ciphertext; stop the API, back up, run `python scripts/rotate_master_key.py`, start it again: PDFs still download.
8. **Attack suite:** `python scripts/attack_suite.py` prints what stopped each of 16 attacks ([results](docs/attack_suite.md)).

## Documents

[`docs/architecture.md`](docs/architecture.md) (diagrams), [`docs/threat_model.md`](docs/threat_model.md), [`docs/assumptions.md`](docs/assumptions.md), [`docs/evaluation.md`](docs/evaluation.md) (upload checking and anomaly model, with honest caveats), [`docs/attack_suite.md`](docs/attack_suite.md). Screenshots from the browser test are in `docs/screenshots/`.

## Checks

```powershell
.\.venv\Scripts\python.exe -m pytest --cov=app    # backend tests
.\.venv\Scripts\python.exe -m ruff check .; .\.venv\Scripts\python.exe -m black --check .
.\.venv\Scripts\python.exe -m bandit -q -r app scripts -ll
cd frontend; npm test; npm run build; npm run lint
.\scripts\check.ps1 -Full                        # everything CI runs, in one go
cd frontend; npm run build; npm run e2e         # real-browser demo script + accessibility check (own seeded database on :8002)
```

## Troubleshooting

- **`CERTIFICATE_VERIFY_FAILED` from pip or git** (common on networks that inspect TLS): Python and Node ship their own CA lists. Use the Windows certificate store instead of disabling verification.
  - pip: `python -m pip --python .venv\Scripts\python.exe install ...` using a recent system pip (26+), or `pip install truststore` first.
  - git: `git -c http.sslBackend=schannel clone|push ...`
  - npm/Node: set `NODE_USE_SYSTEM_CA=1`.
- `py -0p` may list a Python that is no longer installed; check with `Test-Path` on the listed path.
