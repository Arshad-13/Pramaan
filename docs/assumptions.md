# Assumptions and trust boundaries

What the design takes for granted. If one of these is false, the matching guarantee is weaker.

## Trusted

- **The server process and its host.** Keys are decrypted in memory (the master key for data keys, a doctor's key while signing). Someone who controls the running process can misuse them.
- **The admin who creates doctors.** A doctor account exists only because an administrator vouched for it (registration number, clinic). Pramaan does not check a registration number against a medical council.
- **The doctor's signing password.** It is the only thing between the stored private key and the signature. Doctors choose it themselves; administrators never see it.
- **The pharmacist's eyes.** The system tells a pharmacist what the doctor signed; the pharmacist still hands over the medicine and should dispense according to the verified record, not the paper.
- **The patient's phone or account.** The dispense PIN is shown in the patient's account; whoever holds it can authorise a dispense.

## Not assumed

- That a QR code, PDF or photo is genuine (it is verified every time).
- That the database or the storage folder is private or unmodified (payloads are encrypted, hashed and cross-checked; the log is chained).
- That the network is friendly: requests carry cookies with CSRF protection, and the demo is meant to be fronted by HTTPS if used beyond one machine.

## Data and models

- Drug, dose-limit and schedule data are small demo tables, approximately right, not clinically validated.
- All anomaly-model data is simulated. The model is a safety net that nudges the risk score by at most 40 points; it never blocks issuing.
- Upload checking is evaluated on generated files; its photographs are simulated, not real phone captures.

## Operational

- Keys live in `.env` and `secrets/` (git-ignored). Losing the master key makes stored prescriptions unreadable; rotate it with `scripts/rotate_master_key.py` on a backed-up system.
- Time comes from the server clock (a frozen clock is a test/demo feature only).
- Python 3.11, Node 20.19+ or 22+, Windows is the tested platform.
