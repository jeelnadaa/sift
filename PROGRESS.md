# Sift (Inbox Agent) — Progress Log

Read this first in every new session. Spec: `Inbox_Agent_Master_Prompt.md`.
Rule: commit every change to git, never push (the owner pushes).

## Project
- Name: **Sift** (repo `jeelnadaa/sift`). Spec calls it "Inbox Agent".
- Domain: solarquack.in (subdomain TBD).

## Status
| Track | State |
|-------|-------|
| Design (landing, web UI, mobile) | v1 done, see `design/README.md` (awaiting owner feedback) |
| Phase 0 (setup) | not started |
| Phases 1–5 | not started |

## Log (newest last)
- 2026-10-24 — Chose name Sift. Started design track: static HTML prototypes in `design/`.

- 2026-10-24 — Design v1 built: shared tokens/components, landing page (motion), web UI (13 routes), mobile gallery (20 screens). Verified over local http server, no console errors. Committed locally, not pushed.

## Decisions
- Designs are static HTML/CSS/JS prototypes (no build step) so they open by double-click and serve as the visual reference for the React web UI and Compose app.
- Fonts: Clash Display (display), Satoshi (body) via Fontshare; JetBrains Mono (data) via Google Fonts.

## Open questions
- Hosting choice, Android package name, Firebase/GCP project IDs (needed before Phase 0).
