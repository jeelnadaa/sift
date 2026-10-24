# Sift Design System

Single source of truth for how Sift looks and moves. The HTML prototypes in `design/` implement it; the React web UI and the Jetpack Compose app must match it. If code and this file disagree, fix one of them in the same commit.

Tokens live in `design/shared/tokens.css`, components in `design/shared/components.css`.

## 1. Principles

1. **Signal over noise.** The UI is dark and quiet. Lime appears only where something is active, urgent-safe or primary. If everything glows, nothing does.
2. **One color per meaning.** Priority tiers each own a color and it is never reused for decoration.
3. **Squarish, not boxy.** Corners are small and consistent. Nothing is a pill, except round dots and avatars of people that are circles by nature.
4. **Calm motion.** Motion explains (a notification arrives, a sidebar collapses). It is never required to understand the UI and respects `prefers-reduced-motion`.
5. **Honest states.** Blocked, reconnect, silenced and AI-off states are always visible and always say what to do next.

## 2. Color

Dark theme only for now.

| Token | Value | Use |
|---|---|---|
| `--bg` | `#0a0a0b` | App background |
| `--bg-2` | `#101012` | Sidebar, inset panels, inputs |
| `--surface` | `#151518` | Cards, rows on hover |
| `--surface-2` | `#1c1c20` | Selected rows, tag/chip fills |
| `--line` / `--line-2` | `#26262b` / `#34343b` | Dividers / control borders |
| `--text` | `#f4f3ee` | Primary text |
| `--text-2` | `#a9a9b1` | Secondary text |
| `--text-3` | `#6e6e78` | Hints, timestamps, section labels |
| `--signal` | `#c8ff3d` | Brand, primary buttons, active nav, valid, done |
| `--signal-ink` | `#10150a` | Text on signal |
| `--urgent` | `#ff5a3c` | Urgent tier, errors, reconnect |
| `--normal` | `#6ea8ff` | Normal tier |
| `--digest` | `#b79cff` | Digest tier, groups |
| `--silent` | `#5b5b64` | Silenced |
| `--warn` | `#ffb938` | Deadlines, blocked accounts, AI-off hint |
| `--acc-1..4` | `#ff8a5b #4ad6c4 #f6d365 #ff6fae` | Account labels, assigned in connect order |

Tinted fills (tags, banners) use the color at 12–14% alpha with the full color as text. Contrast of body text on `--bg` is above 15:1; `--text-3` is for non-essential text only.

## 3. Typography

| Role | Font | Notes |
|---|---|---|
| Display | **Clash Display** 500/600/700 | Headlines, page titles, wordmark, big numbers, avatars |
| Body and UI | **Satoshi** 400/500/700 | All interface text, buttons, pills, tables, inputs, timestamps |
| Code | **JetBrains Mono** 400/500 | Only real code: regex, Gmail query strings, API keys, model IDs (`.code`) |

Rules:
- Satoshi is the default for everything that is not a headline. Do not use monospace for timestamps, labels or counts. Use `font-variant-numeric: tabular-nums` (`.mono` class) so digits align.
- Display tracking is loose-ish: `letter-spacing: -.005em` for headings, at most `-.035em` for hero sizes, `word-spacing: .08em` (`.12em` hero). The wordmark is `letter-spacing: .06em` with a 12px gap between mark and text.
- Section labels: Satoshi 700, 10.5px, uppercase, `.14em` tracking, `--text-3`.
- Sizes: page title 28, section title 22, body 15, row subtitle 13–14, pill 11.5–12.5, mobile body 12.5–13.5.
- Clash Display and Satoshi are self-hosted in `design/shared/fonts/` (declared in `shared/fonts.css`), so they load offline and from `file://`. Request them from Fontshare separately, never in one URL, which returns only the first family. JetBrains Mono loads from Google Fonts. Reuse the same woff2 files in the real apps.

## 4. Shape and spacing

| Token | px | Use |
|---|---|---|
| `--r-xs` | 4 | Tags, tiny marks |
| `--r-sm` | 6 | Chips, small buttons, toggle knob, tooltips |
| `--r` | 8 | Buttons, inputs, nav items, avatars, toggles, search |
| `--r-lg` | 10 | Cards, lists, banners, sheets (top corners 14) |
| `--r-xl` | 14 | Large landing panels |

- Device mockup frames: 28 (mobile gallery) to 32 (landing). Dots and the cursor glow are the only circles.
- Spacing scale: 4, 6, 8, 10, 14, 16, 20, 28, 32. Page padding 28/32 on web, 14–18 on mobile. Row padding 14×16.
- Borders are 1px `--line`; emphasis borders use `--line-2`. Status borders use the status color at ~40% alpha.

## 5. Components

- **Button**: height 40 (small 32), radius `--r`, weight 700. Primary = signal fill; ghost = `--line-2` border; danger = urgent tint. Hover adds a soft signal halo, press scales to .97.
- **Pill / chip / tag**: squarish (`--r-sm` / `--r-xs`), **text always starts with a capital letter** ("Assessment link", not "assessment_link"; never show snake_case). Query chips that mirror Gmail syntax (`from:kotak`) are the one exception and stay as typed. Tags are filled and informational; chips are outlined and interactive; `.on` chips are inverted (light fill).
- **Priority dot**: 8px circle in tier color; urgent pulses.
- **Account label**: 8px rounded square in the account color plus capitalized name.
- **Row** (mail, rule, folder): dot, avatar, bold sender with tags, one-line subject, account label, time. Unread subject uses `--text`.
- **Card**: `--surface`, 1px `--line`, radius `--r-lg`, padding 20.
- **Toggle**: 42×24, radius `--r`, square-ish knob.
- **Input**: height 42, radius `--r`, focus ring is a 4px signal halo at 10%.
- **Banner**: tinted fill + status border; always has the next action as a button on the right.
- **Locked (AI-off)**: dimmed to 45% with the label "Add an API key to enable" in `--warn`. Keep the non-AI alternative visible beside it.
- **Timeline**: 2px vertical line, 12px event dots (done = signal, urgent = urgent, pending = silent), tag + time + bold title.

## 6. Layout

### Web
- Grid: sidebar + main. Sidebar is **264px expanded, 76px collapsed (icons only)**, animated `.35s`. Toggle with the chevron button or the `[` key; the choice persists in `localStorage` (`sift.sidebar`), and screens narrower than 1000px start collapsed.
- Sidebar sections, each separated by a hairline and a small uppercase label (the label becomes the hairline when collapsed):
  - **Inbox**: Feed, To-do, Opportunities, Groups
  - **Organize**: Folders, Search, Senders
  - **Control**: Rules, Silenced, Onboarding scan
  - **Account**: Accounts, Token usage, Settings
- Active item: `--surface-2` fill, signal icon, 3px signal bar on the sidebar edge. Counts are plain numbers (urgent counts in `--urgent`); when collapsed they become a red dot and the item name shows as a tooltip.
- The sidebar shows no AI status. AI state lives in Settings and on locked features only.
- Top bar: sticky, page title left, global search right.
- Icons: 18px, 1.6 stroke, rounded caps, `currentColor` (inline SVG sprite in the page).
- **Built app (`web/`, Phase 2c):** React implementation of this layout. It imports `design/shared/tokens.css` and `components.css` directly (one source of truth) and adds `web/src/styles.css` for layout. Differences from the prototype: Search and Senders are not in the sidebar yet (Phase 3); under **Organize** the top-level folders are listed (8 at most, indented, color square + unread count) as **drop targets**: drag any mail row onto one to file it (it highlights with a 12% signal tint). Folder tree rows are draggable onto each other to nest; the tree ends with a dashed "Drop a folder here to move it to the top level" target. Group rows use `.group-row` with a ▤ avatar, "N mails", unread and urgent tags. `.split` (list + detail) stacks to one column below 1180px. Dialogs use a 60% scrim and `--r-xl` corners; a short toast (inverted colors) confirms actions.

### Mobile (Android, Compose)
- 300×620 reference frame, status bar, app bar (title + icon buttons), content, bottom tab bar (Feed, Deals, To-do, Folders, More).
- Tab selection is a 6px-radius tinted indicator behind the icon, not a pill.
- Bottom sheets round the top corners only (14). Dialogs and sheets dim content with a 55% scrim.
- Notifications use three channels (urgent, normal, digest), each with a colored dot and an uppercase "SIFT · TIER" header, with action buttons as small squarish chips.

## 7. Motion

| Where | Motion | Timing |
|---|---|---|
| Hero headline | Masked line reveal, translateY 110% to 0 | 1.1s `--ease-out`, 120ms stagger |
| Hero background | Canvas sieve: mail falls, noise fades at the mesh, signal passes and glows | Continuous |
| Stats | Count-up | 1.2s ease-out cubic |
| Sections | Fade and rise on scroll (IntersectionObserver) | .9s, 90ms stagger |
| Marquee | Linear loop | 38s |
| Cursor glow | Soft signal radial that follows the pointer | .5s |
| Phone mockup | Notifications drop in sequentially | .9s each |
| Cards | Lift 6px on hover | .5s |
| Sidebar | Width tween on collapse | .35s |
| Pages | Rise 14px on route change | .5s |

Easing: `--ease` `cubic-bezier(.2,.8,.2,1)`, `--ease-out` `cubic-bezier(.16,1,.3,1)`. Under `prefers-reduced-motion` all durations collapse to ~0.

## 8. Voice and copy

- Plain, short, second person. "Add an API key to enable", not "AI features unavailable".
- Blocked account copy is fixed: "This account may be blocked by its administrator (common for college or work accounts)."
- Never show internal identifiers (`needs_reconnect`, `assessment_link`). Show "Needs reconnect", "Assessment link".
- Never imply mail was deleted. Silenced mail is "stored and searchable".

## 9. Accessibility

- Visible focus ring (2px signal, 2px offset) on every interactive element.
- Never rely on color alone: tiers also carry a text tag, statuses carry a label.
- Touch targets on mobile at least 44px in the real app (the mockups compress them).
- Text on signal uses `--signal-ink`.

## 10. Screen inventory

Web routes (`design/web/index.html`): `#feed #todo #opps #groups #folders #search #senders #rules #silenced #scan #accounts #usage #settings`. Mobile (`design/mobile/index.html`): welcome, battery exemption, grouping prompt, onboarding scan, feed, mail detail, notification shade, to-do, opportunities, company timeline, groups, group detail, folders, search, rules list, rule editor, silenced, accounts, usage, settings. Landing: `design/landing/index.html`.

Not designed yet: mobile senders, compose/reply, snooze, light theme. The built web app has a plain-text mail detail (`/app/mail/:id`: tags, sender, extracted card, filing chips, body as text) until the Phase 3 reader is designed.

## 11. Changing the design

1. Change the token or component CSS first, then the screens.
2. Update this file in the same commit.
3. Log the change in `PROGRESS.md`.
