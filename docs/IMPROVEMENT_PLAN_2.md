# Improvement plan 2: usability, design and new features

Started after the security review (`docs/security_review.md`). Source: a screen-by-screen look at the app (light, dark, phone width), the page code and the API routes. The product register, personality and design principles in `PRODUCT.md` still apply: calm, exact, official; the verdict is the product; status is never colour alone.

Ground rule for every phase: **no change may weaken a security property or break the demo path.** Each phase ends with `scripts/check.ps1 -Full` green; frontend phases also end with the browser tests and a look at fresh screenshots.

## Phases

| Phase | Scope | Notes |
|---|---|---|
| **K1** Backend foundation | Schema v2 with an in-place migration (alert workflow, MFA columns, superseded link, audit index); `/public-config` (demo mode is a server setting, off by default); explicit session renewal with a hard cap; audit filters, CSV export; alert acknowledge/resolve; user search; pharmacist history; dispense history for patients and doctors; model status | Migration copies the database file first |
| **K2** Clinical features | Drug-interaction rules (data file, classes, severities) wired into risk; "why this score" breakdown; corrected prescriptions that supersede the old one | Interaction data is approximate, same disclaimer as the rest |
| **K3** Two-factor sign-in | TOTP (RFC 6238, authenticator apps), recovery codes, step-up on sign-in, enrol and disable on the Account page | No new dependency; secrets encrypted under the master key and re-wrapped on rotation |
| **K4** Design system and shell | Tokens, spacing scale, density, new dashboards per role, sidebar footer, verdict next-action line, empty states, skeletons | Impeccable product register: restrained colour, one family for UI |
| **K5** Feature screens | Filters and search everywhere, relative times, history pages, alert workflow, scanner torch and camera switch, Enter-to-verify, session warning, MFA screens, PIN full screen, stepper for new prescription, repeat and correct, breakdown view, model health, audit export | |
| **K6** Languages | English, Hindi and Gujarati for the main flows (sign-in, navigation, verify, patient PIN, account) | Short UI strings only; native-speaker review recommended before real use |
| **K7** Proof | More browser tests, `scripts/bench.py` (latency numbers), attack suite extended, docs, screenshots, fresh-clone check | |

## Deliberately not done

- **Lock a prescription to one pharmacy.** Changes the consent model and the QR flow; the PIN already limits replay.
- **Offline-verifiable QR.** Needs a new signed compact format and a client-side verifier; too large to add safely.
- **Removing `'unsafe-inline'` from the style policy.** The toast library injects a style element at run time; verified need for a nonce, not worth the risk.
- **Real email or SMS.** Out of scope for an offline demo; the in-app alert workflow covers the same need locally.

## Outcome

All seven phases were completed. `scripts/check.ps1 -Full` passes (formatting, lint, `bandit`, backend tests, frontend lint, build and tests).

| Measure | Result |
|---|---|
| Backend tests | 1,027 passing, 97% line coverage of `app/` |
| Frontend tests | 159 passing (12 files) |
| Browser tests | 12 passing in a real browser, including axe accessibility checks in light and dark themes and a phone-width check |
| Attack suite | 19 of 19 blocked (the 16 of the specification, plus corrections, two-factor and alert roles) |
| Anomaly model after the interaction-aware retrain | pooled ROC-AUC 0.907, PR-AUC 0.596 on unseen scenarios (`docs/evaluation.md`) |
| Latency | see `docs/performance.md` (verify a QR code about 19 ms; verify an uploaded PDF about 1.4 s) |
| Main script size | 536 kB (162 kB gzipped); other screens load on demand |

Things the browser tests caught that unit tests did not: the phone-width header overflowing once a language selector was added, a malformed definition list on the dashboard, filter-count text below the contrast limit, and the "original was withdrawn" note disappearing after signing a correction (the list refetched and the old prescription then read as withdrawn).

Known limits: Hindi and Gujarati cover the main flows only and need a native-speaker review; interaction data is approximate; the main script is above 500 kB and could be split further.

