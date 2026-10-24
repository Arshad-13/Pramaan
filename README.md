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

# 3. Run API (:8000) and Vite dev server (:5173) together
.\scripts\run_dev.ps1
```

Open <http://localhost:5173>. For a single-process build, run `npm run build` in `frontend/` and then `uvicorn app.main:app`; FastAPI serves the built app on <http://localhost:8000>.

The app **refuses to start** if `.env` is missing or contains placeholder or malformed secrets.

## Checks

```powershell
.\.venv\Scripts\python.exe -m pytest --cov=app    # backend tests
.\.venv\Scripts\python.exe -m ruff check .; .\.venv\Scripts\python.exe -m black --check .
.\.venv\Scripts\python.exe -m bandit -q -r app scripts -ll
cd frontend; npm test; npm run build; npm run lint
```

## Troubleshooting

- **`CERTIFICATE_VERIFY_FAILED` from pip or git** (common on networks that inspect TLS): Python and Node ship their own CA lists. Use the Windows certificate store instead of disabling verification.
  - pip: `python -m pip --python .venv\Scripts\python.exe install ...` using a recent system pip (26+), or `pip install truststore` first.
  - git: `git -c http.sslBackend=schannel clone|push ...`
  - npm/Node: set `NODE_USE_SYSTEM_CA=1`.
- `py -0p` may list a Python that is no longer installed; check with `Test-Path` on the listed path.
