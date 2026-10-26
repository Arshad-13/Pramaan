# Pramaan: critical audit and improvement plan

Written Mon 26 Oct 2026, five days before submission and one day before feature freeze (end of Tue 27 Oct).
Method: read the whole backend and frontend source, the screenshots in `docs/screenshots/`, ran the design
detector (`detect.mjs`, zero findings), and judged the product against `PRODUCT.md`. Severity: P0 blocks a task,
P1 causes real difficulty or a standards failure, P2 is a noticeable gap, P3 is polish.

Ground rule for every phase: **no change may weaken a security property or break the demo path.** Each phase ends
with `scripts/check.ps1 -Full` green and a commit. Anything risky is cut, not rushed.

## Verdict in one paragraph

The cryptography, audit chain, verification pipeline and attack suite are the strong part: fail-closed config,
signed-payload-wins semantics, atomic dispense, constant-time checks, CSRF bound to the session. The weak part is
everything around the happy path: the session silently dies after 30 minutes, there is no account page, the verdict
screen sends mixed messages when a record is clean but carries a soft risk note, the app has no error boundary,
page titles or 404, and the server has no request IDs or readiness check. None of this is dangerous; all of it is
what separates "a student project that works" from "a product".

## Findings

### Frontend: design and product

| # | Sev | Finding | Where |
|---|-----|---------|-------|
| F1 | P1 | A **Verified** verdict can sit above an amber "Why this was flagged" box, with a ticked "Risk check" row. The product principle is "a verdict a user can trust without reading documentation"; mixed signals at the highest-stakes screen break it. A below-threshold note is information, not an alarm. | `Verify.tsx` `RiskNotes`, `docs/screenshots/04-pharmacist-verified.png` |
| F2 | P1 | Session expiry is invisible. Tokens last 30 minutes; `api()` has no 401 handling, and `['me']` is cached for 60 s. A doctor who spends 35 minutes on a prescription gets "Not authenticated." and a dead form. | `lib/api.ts`, `lib/auth.tsx` |
| F3 | P1 | No account page. The backend has change-password (and it revokes every session) but no screen reaches it; users cannot see their own role, licence number or patient code outside the dashboard. | missing |
| F4 | P2 | Under a TAMPERED or REVOKED verdict the card still says "Dispense according to this verified record, not the paper." Right in a hold-and-escalate flow it reads like an instruction to dispense. | `VerifiedRecord.tsx` |
| F5 | P2 | Every page has the title "Pramaan" (WCAG 2.4.2), and route changes do not move focus or announce the new page (WCAG 2.4.3 in practice for SPA screen-reader users). | `index.html`, `App.tsx` |
| F6 | P2 | The Verify tabs use `role="tab"` without the rest of the pattern: no arrow-key navigation, no roving tabindex, no `tabpanel`/`aria-controls`. A half-implemented ARIA pattern is worse than plain buttons. | `Verify.tsx` |
| F7 | P2 | No error boundary (a render error or a failed lazy chunk is a white screen) and no 404 page (unknown URLs silently redirect to the dashboard). | `App.tsx` |
| F8 | P2 | `RISK_REVIEW_AT = 60` is copied from the server config; a second `greeting()` duplicates `lib/greeting.ts`. Drift waiting to happen. | `Dashboard.tsx` |
| F9 | P2 | One 606 kB JS chunk carries React, the router, query, motion, zod and the dashboard on first load. | `vite.config.ts` |
| F10 | P3 | No `theme-color`, Open Graph or app-name metadata; link previews of the deployed demo are blank. | `index.html` |

Working well, to keep: the verdict-first layout, check timeline that names the failing check, tamper overlay,
icon + text + colour status, token system with a real dark theme, reduced-motion handling, 116 unit tests and axe
checks in both themes. The detector found no slop tells.

### Backend

| # | Sev | Finding | Where |
|---|-----|---------|-------|
| B1 | P1 | No request correlation or access log. When a verification misbehaves during the live demo there is nothing to grep. Add a request ID (response header + log line, no PII, no bodies). | `main.py` |
| B2 | P1 | `/api/health` is liveness only. Nothing tells an operator that the DB, audit key or anomaly model is unusable. Add `/api/ready` that answers ok/degraded and nothing more. | `main.py` |
| B3 | P1 | Schema is created with `create_all` and never versioned. A model change after submission would silently diverge from an existing `pramaan.db`. Stamp `PRAGMA user_version` and fail closed on mismatch. | `db.py` |
| B4 | P2 | `SessionLocal()` builds a new `sessionmaker` on every request. | `db.py` |
| B5 | P2 | CORS origins are parsed twice (`main.py` and `Settings.cors_origin_list`). | `main.py` |
| B6 | P2 | Login returns the JWT in the JSON body as well as the HttpOnly cookie. Scripts and the attack suite use it, so it stays, but it is an **accepted, documented** trade-off. | `routers/auth.py` |
| B7 | P2 | Coverage is only measured in CI and not on a target. Establish the number for `app/core` and `app/services`. | CI |
| B8 | P3 | `style-src 'unsafe-inline'` in the CSP. Probably removable (React and Motion set styles through the CSSOM), but verifying needs the e2e suite; list it, do not risk it. | `main.py` |

Working well: config fails closed, argon2id + dummy-hash timing, token version revocation, role read from the DB on
every request, CSRF HMAC bound to the session id, upload size/slot limits, layered rate limits, strict Pydantic
input, BEGIN IMMEDIATE, audit chain with signed checkpoints, key rotation script.

## Phases

| Phase | Scope | Risk | Done when |
|-------|-------|------|-----------|
| **I1** Trust and clarity | F1, F4, F8 (verdict screen copy and hierarchy, single source for the threshold and greeting) | low | tests updated, screenshots still tell one story |
| **I2** Sessions and account | F2, F3 (global 401 handling, session-ended notice, `/account` page with change password) | medium | e2e sign-out and expiry paths pass |
| **I3** Frontend resilience | F5, F6, F7, F10 (titles, focus and announcements on navigation, real tabs, error boundary, 404, metadata) | low | axe still clean in both themes |
| **I4** Backend operability | B1, B2, B3, B4, B5 (request IDs, readiness, schema version, session factory) | low | new tests; attack suite 16/16 |
| **I5** Performance | F9 (vendor chunking, lazy Motion), measure before and after | low | smaller first load, e2e green |
| **I6** Proof | B7, B6 documentation, re-run the attack suite, fresh-clone test, regenerate screenshots, update README, architecture and checklist | none | all gates green, CI green on GitHub |

Cut line: if time runs short after I4, I5 is dropped; I6 is never dropped.

## Outcome (Tue 27 Oct)

| Phase | Result |
|-------|--------|
| I1 | A Verified verdict now shows background notes under a calm "Worth knowing" heading; only flagged verdicts get the amber "Why this was flagged" box. The record card's guidance follows the verdict (the spec sentence only when the prescription is cleared). The server now says which prescriptions are `flagged`, so the 60-point threshold exists in one place only. |
| I2 | A 401 on any signed-in request ends the session in the UI with a toast and a redirect to sign-in. New `/account` page (details, patient code, change password); the account block in the sidebar links to it. Change-password is now rate limited per user (found while reviewing: the current-password check was an unthrottled oracle for a stolen session). |
| I3 | Per-page tab titles; focus moves to the main region after navigation; the Verify entry-method tabs follow the full ARIA tabs pattern (arrow keys, Home/End, roving tabindex, tabpanel); error boundary; a real 404 page; theme-colour and Open Graph metadata. |
| I4 | `X-Request-ID` on every response and a PII-free access log; `GET /api/ready` (ok or degraded, nothing else) feeding the dashboard's Service badge; schema version stamped and enforced; cached session factory; single CORS parse. |
| I5 | The sign-in page no longer loads the animation library. Main chunk 606 kB to 488 kB raw, 187 kB to 150 kB gzipped (-20%). Further cuts (zod, react-dom) would need dropping libraries, not worth the risk on freeze day. |
| I6 | See the final report in the commit and README. |

Not done, deliberately: B8 (removing `'unsafe-inline'` from the CSP; needs full browser verification), a real migration tool, a "forgot password" flow (needs email delivery, out of scope for an offline demo), and sliding session renewal (the 30-minute fixed lifetime is a security choice; the new session-ended message makes it visible instead of silent).
