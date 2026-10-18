# Product

## Register

product

## Users

- **Pharmacist** (primary, highest-stakes screen): at a counter with a queue, bright light, often on a phone or a shared PC, scanning a prescription. Needs a trustworthy yes/no in seconds and a clear "dispense per this verified record".
- **Doctor**: at a desk between patients; issues signed prescriptions, must understand risk warnings quickly and enter a signing password.
- **Patient**: occasional, non-technical; views prescriptions and shows a short dispense PIN on a phone.
- **Admin / auditor**: infrequent, deliberate; manages accounts, reviews security events, verifies the audit chain.

Job to be done: establish, quickly and with evidence, that a prescription is genuine, unaltered, unused and not suspicious, and leave a tamper-evident record of every decision.

## Product Purpose

Pramaan is a tamper-proof prescription verifier (academic project, AI 331, SVNIT Surat). Doctors issue digitally signed prescriptions with a QR code; pharmacists verify and dispense; the system detects tampering, replay, revocation, expiry and abnormal prescribing, and logs everything in a tamper-evident audit chain. Success: a verdict a user can trust without reading documentation, and a demo that makes the evidence visible (which check failed, which cell was edited).

## Brand Personality

Calm, exact, official. Three words: **assured, precise, plain-spoken**. Emotional goal: confidence under time pressure. The interface should feel like a well-made instrument or a certificate authority, never a toy and never alarmist.

## Anti-references

- Generic SaaS dashboard templates: hero-metric cards, identical icon-card grids, purple/blue gradients.
- Glassmorphism, neon "cyber-security" dark UIs, hacker-green terminals.
- Hospital-software clutter (dense grey forms, tiny type, tab soup).
- Colour-only status signalling; alarm-red screens for non-critical states.
- Decorative motion that does not convey state.

## Design Principles

1. **The verdict is the product.** The result of a verification is the largest, calmest, clearest thing on screen; evidence follows beneath it.
2. **Show the evidence.** Every verdict lists the checks behind it; every mismatch points at the exact thing that failed (the cell, the field, the log entry).
3. **Authority comes from the signed record.** Always present the verified record as the source of truth ("what you see is what you signed"), not the paper.
4. **Never rely on colour alone.** Icon + text + colour for every status; a colour-blind user must read the same verdict.
5. **Familiar controls, earned moments.** Standard product patterns everywhere; expressive design is reserved for the few moments that carry the story (the seal, the tamper overlay, the audit chain).

## Accessibility & Inclusion

WCAG 2.2 AA minimum: body text 4.5:1 contrast, visible focus rings, full keyboard operation, `aria-live` announcements for verification results, `prefers-reduced-motion` respected (final state shown instantly), touch targets at least 44px on the Verify flow, usable at phone width. Status always conveyed by icon and text as well as colour.
