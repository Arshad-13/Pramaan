# Attack suite results

Produced by `python scripts/attack_suite.py --markdown docs/attack_suite.md` against the seeded
demo database. The same attacks run as tests in `tests/test_attack_suite.py`.

| # | Attack | Control that caught it | Result | Evidence |
|---|---|---|---|---|
| 1 | Flip one bit of the stored payload in the database | AES-GCM authentication tag + hash check | Blocked | TAMPERED ['DB_RECORD_ALTERED'] |
| 2 | Extend validity by editing the expires_at column | Plain columns cross-checked against the signed payload | Blocked | TAMPERED ['DB_RECORD_ALTERED'] |
| 3 | Edit one dose digit in a rendered image (500 mg -> 800 mg) | Render-and-diff + OCR against the signed content; dispense hold | Blocked | TAMPERED field=['med_0_dose'] read=['800 mg'], dispense afterwards=409 |
| 4 | White-box overlay on the PDF text (new dose drawn over the old) | PDF text layer vs. rendered page vs. signed text | Blocked | TAMPERED ['HIDDEN_TEXT_OR_OVERLAY', 'CONTENT_MISMATCH'] |
| 5 | Add an extra medicine line below the table | Blank rows must stay blank (extra-content check) | Blocked | TAMPERED ['med_2_name', 'med_2_dose', 'med_2_freq', 'med_2_days'] |
| 6 | Forge one character of the QR signature | ECDSA signature + QR/hash cross-check | Blocked | TAMPERED ['INVALID_SIGNATURE'] |
| 7 | Swap in the QR code of another prescription | The page is checked against the record its own QR names | Blocked | TAMPERED ['CONTENT_MISMATCH'] |
| 8 | Replay the same QR at a second pharmacy | Atomic dispense + cross-pharmacy alert | Blocked | second scan=ALREADY_USED, MEDIUM alerts=1 |
| 9 | Concurrent double dispense (20 threads at once) | Conditional UPDATE + UNIQUE(rx_id, fill_no) | Blocked | successes=1 of 20, dispense rows=1 |
| 10 | Redeem a photographed QR without the patient's PIN | Patient-consent PIN + 3-try lock | Blocked | no PIN=400, wrong PINs=[403, 403, 403], right PIN after lock=423 |
| 11 | Brute-force a login (many wrong passwords) | Rate limit (IP + account) and account lockout | Blocked | codes=[401, 401, 401, 401, 401, 429, 429], correct password after lock=401 |
| 12 | Brute-force the signing password | Signing-key lockout + MEDIUM alert | Blocked | codes=[403, 403, 403, 403, 403, 423, 423], correct password while locked=423 |
| 13 | Use a stolen token after logout and after deactivation | token_version revoked on logout; role and status read from the DB each request | Blocked | before=200, after logout=401, after deactivation=401 |
| 14 | A pharmacist calls doctor and admin endpoints | Role x endpoint matrix (require_role) | Blocked | statuses=[403, 403, 403, 403, 403, 403, 403] |
| 15 | Edit an audit row; edit and recompute; truncate the tail | HMAC hash chain + signed checkpoints + external anchor | Blocked | edit: detected, recompute: detected, truncate: detected |
| 16 | Swap the anomaly model file for another | Model signature verified before unpickling | Blocked | warnings=['MODEL_UNAVAILABLE'], HIGH alerts so far=1 |

**16 of 16 attacks detected or blocked.**
