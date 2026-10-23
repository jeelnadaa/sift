# Sift design prototypes

Static HTML/CSS/JS, no build step. They are the visual reference for the React web UI and the Jetpack Compose app.

## View them
Open over HTTP so the shared CSS and web fonts load:

    cd design && python -m http.server 8765

- Landing:  http://localhost:8765/landing/index.html
- Web UI:   http://localhost:8765/web/index.html  (hash routes: #feed #todo #opps #groups #folders #search #senders #rules #silenced #scan #accounts #usage #settings)
- Mobile:   http://localhost:8765/mobile/index.html  (all Android screens as phone frames)

The rules behind these screens are in [`../DESIGN.md`](../DESIGN.md).

## Design system (`shared/`)
- `tokens.css`: colors, fonts, radii, easing. One color per priority tier (urgent coral, normal blue, digest violet, silent gray) and lime `--signal` as the brand accent. Dark only.
- `components.css`: buttons, chips, tags, rows, toggles, inputs, cards, the greyed-out "Add an API key to enable" state (`.locked`).
- Fonts: **Clash Display** (headlines), **Satoshi** (all UI text), both self-hosted in `shared/fonts/`; **JetBrains Mono** only for code, from Google Fonts. For production, self-host the files instead of the CDN.
- Motion: masked headline reveal, count-up stats, canvas "sieve" hero (mail falls, noise is filtered, signal passes), marquee, scroll-reveal, cursor glow, notification drop-in. All respect `prefers-reduced-motion`.

## Screen coverage (brief section 13)
| Brief item | Web | Mobile |
|---|---|---|
| Landing | yes | n/a |
| Feed with account filter, banners | #feed | Feed |
| To-do | #todo | To-do |
| Opportunities and timelines | #opps | Opportunities, Company timeline |
| Mail detail | not yet (phase 3 reader) | Mail detail |
| Rules and categories, editor with preview | #rules | Rules list, Rule editor |
| Onboarding scan | #scan | Onboarding scan |
| Folders | #folders | Folders |
| Search and filter builder | #search | Search |
| Groups and first-open prompt | #groups | Groups, Group detail, Grouping prompt |
| Silenced | #silenced | Silenced |
| Senders view | #senders | not yet |
| Accounts | #accounts | Accounts |
| Token usage | #usage | Usage |
| Settings, AI key, AI-off state | #settings | Settings |
| Battery exemption onboarding, notification shade | n/a | yes |

## Known gaps
- Mail detail on web, Senders on mobile, compose/reply and snooze screens (phases 3 and 4) are not designed yet.
- Light theme not designed.
- Prototypes use static sample data and are not wired to any backend.
