# Sift (Inbox Agent) — Progress Log

Read this first in every new session. Spec: `Inbox_Agent_Master_Prompt.md`.
Rule: commit every change to git, never push (the owner pushes).

## Project
- Name: **Sift** (repo `jeelnadaa/sift`). Spec calls it "Inbox Agent".
- Domain: solarquack.in (subdomain TBD).

## Status
| Track | State |
|-------|-------|
| Design (landing, web UI, mobile) | v1 done, v2 done, see `DESIGN.md` and `design/README.md` |
| Phase 0 (setup) | not started |
| Phases 1–5 | not started |

## Log (newest last)
- 2026-10-24 — Chose name Sift. Started design track: static HTML prototypes in `design/`.

- 2026-10-24 — Design v1 built: shared tokens/components, landing page (motion), web UI (13 routes), mobile gallery (20 screens). Verified over local http server, no console errors. Committed locally, not pushed.
- 2026-10-24 — Design v2 (owner feedback): Satoshi for all UI text and tabular numerals instead of monospace (JetBrains Mono only for real code); radii cut to 4/6/8/10/14 (no pills); all pill text capitalized, snake_case removed; web sidebar now collapsible (264/76px, `[` key, persisted) with labeled sections Inbox/Organize/Control/Account and SVG icons; removed the AI-on sidebar pill; wordmark and heading tracking opened up; same changes on mobile and landing; themed scrollbars. Wrote `DESIGN.md` (design source of truth). Committed locally, not pushed.
- 2026-10-24 — Fixed Satoshi not loading (Fontshare returned only Clash Display for a combined request, so body text fell back to system font). Fonts now self-hosted in `design/shared/fonts/` + `fonts.css`; verified Satoshi 400/500/700 and Clash Display load. Added `CLAUDE.md` with all standing instructions (session start routine, phase workflow, docs/log rules, git rules, design and product rules).

## Decisions
- Designs are static HTML/CSS/JS prototypes (no build step) so they open by double-click and serve as the visual reference for the React web UI and Compose app.
- Fonts: Clash Display (display), Satoshi (all UI text) via Fontshare; JetBrains Mono only for code. Full rules in `DESIGN.md`.
- Keep `DESIGN.md` in sync with any design change, in the same commit.

## Open questions
- Hosting choice, Android package name, Firebase/GCP project IDs (needed before Phase 0).
