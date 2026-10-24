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
- Display tracking is loose-ish: `letter-spacing: -.005em` for headings, at most `-.035em` for hero sizes, `word-spacing: .08em` (`.12em` hero). The wordmark is the owner's artwork (see **Logo** below), not set in a font.
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
- **Toggle**: 42×24, radius `--r`, square-ish knob. Android: 48×28, `--r-sm` track, 18px square knob with `--r-xs` corners. **Off** is a `--surface-2` track with a `--line-2` border and a light (`--text-2`) knob at the left; **on** is a lime track with a dark knob at the right, so the two states differ in knob position as well as colour (owner, 2026-10-24: the stock switch was round and its off state was one grey blob).

### Logo (owner's artwork, 2026-10-24)
- **Mark:** three lime layers in a rounded square, separated by two S-shaped cuts (mail falling through a sieve). **Wordmark:** custom lowercase "sift" in `--text` with a lime dot on the i and a hooked f. Traced from the owner's image into vector paths; masters in `design/shared/logo/` (`sift-mark.svg`, `sift-wordmark.svg`, `sift-logo.svg`, `sift-logo-on-dark.svg`).
- Lockup: mark, then the wordmark at ~82% of the mark's height, gap ≈ 0.4 × mark height. Always on a dark background; the mark is always `--signal`, the letters `--text`, the dot `--signal`.
- Web: `web/src/Logo.tsx` (`Logo`, `LogoMark`, `LogoWord`); the collapsed sidebar shows the mark only. Favicon `web/public/favicon.svg` (mark on a `--bg` rounded square). Android: `res/drawable/sift_mark.xml`, `sift_wordmark.xml` (login), launcher foreground and the white notification icon use the same mark.
- **Input**: height 42, radius `--r`, focus ring is a 4px signal halo at 10%. **Text inputs wrap**: long values flow onto more lines and the box grows (web `TextField`, up to 8 lines, then it scrolls down; Android `Field`, up to 6 lines), so the whole value can be read without scrolling sideways. Enter / the keyboard's Done key never inserts a line break. Passwords, emails and the server address stay one line.
- **Dropdown** (web `Select`): never the browser's native select. A button styled as an input with a ▾ caret (rotates when open); the menu is a `--surface-2` card, `--line-2` border, `--r-lg` corners, soft shadow, options with an optional hint line in `--text-3`, the active option tinted `--surface`, the chosen one in signal and bold. Keyboard: Enter/Space/arrows open, arrows move, Home/End, typing a letter jumps, Enter picks, Escape closes.
- **Confirm and input dialogs** (web `confirmDialog` / `inputDialog`): never the browser's confirm or prompt. Every delete or remove asks in the app's own modal: the title names exactly what goes ("Delete the Acme timeline?"), one sentence says what stays (mail is never deleted), Cancel is a ghost button, the action is a danger button with a specific verb ("Delete rule", "Remove account").
- **Banner**: tinted fill + status border; always has the next action as a button on the right.
- **Locked (AI-off)**: dimmed to 45% with the label "Add an API key to enable" in `--warn`. Keep the non-AI alternative visible beside it.
- **Conversation (reader, Phase 3a)**: one card per message (`--surface`, `--line`, `--r-lg`), oldest first. Header row: avatar, sender in bold, an "Unread" tag, "to …" when open or the snippet when closed, 📎 when it has attachments, relative time (full date on hover). The newest, the opened and unread messages start open; others open on click. The mail's own HTML is shown **in the app's colours** (owner, 2026-10-24): the `--surface` card colour, `--text`, Satoshi for all text (code stays monospace), links in `--signal`. Mail that sets its own colours (newsletters, receipts) is inverted as a whole so white paper becomes the card colour and black text becomes `--text`, with pictures inverted back so they look as sent. "Original colours" under each message shows it exactly as the sender styled it (light). The frame is transparent and stays invisible until its document has loaded, so nothing flashes white while it arrives (web and Android). A warn banner above says how many remote images were blocked, with "Load images". Attachments are tiles in a grid (icon, name, size, View for images, Download).
- **Search page (web, Phase 3b)**: a card holding the search box (growing text field with a suggestion menu styled like the dropdown: Recent, Saved, Senders, Folders, Tags), a Keywords / By meaning chip pair (By meaning greyed with the tooltip "Add an API key to enable" when AI is off), the parsed chips (inverted `.on` chips; Sift filters marked with ◆; each chip has ¬ to negate and ✕ to remove; negated chips use `.chip.neg`), quick filter chips and dropdowns, a note (`.search-note`: `--bg-2` box, 2px `--line-2` left rule, 12.5px `--text-3`) saying ◆ Sift filters only see mail Sift has seen while Gmail syntax searches all mail, the Gmail query in a code box with Copy, and the plain-English box (`.locked` without a key). Saved searches as chips below (📌 pinned, 🔔 notifies). Results: numbered paged rows (Gmail searches show "Page N · more after this page", no total, because Gmail only estimates); searched words highlighted with a 25% signal `mark`; a match-percentage tag in meaning mode; a "Gmail only" tag for older mail; checkboxes for bulk actions (selection banner with File in folder, Tag, Clear). Phone: the same controls stacked, results load as you scroll.
- **Mail actions (Phase 3c)**: a toolbar row on the mail page, ghost small buttons in reading order: Archive (or Move to inbox), Mark read/unread, ☆ Star / ★ Starred, Label…, Snooze…, Spam, and Trash as the only danger button, last. Archive, trash, spam and snooze leave the page (back to the list). A toast confirms and offers "press Z to undo" for 6 s. Permission: the first action in a read-only account opens a dialog "Allow Sift to change mail?" listing each account with "Allow in Google" (opens Google in a new tab), then "I've allowed it, try again". Accounts show a `Can change mail` (ok tag) or `Read-only` tag, with an "Allow changes" button. Snooze picker: a list of presets with their weekday and time on the right (`.pick` rows), then a date-time field. Phone: one full-width **Actions** primary button under the mail's facts opens a bottom sheet (`--surface`, 14px top corners, scrolls): sections Gmail (archive, read state, star, label, snooze), Organize (file in folder, last used folder, company, to-do, calendar), Sift (ignore/not like this, open in Gmail) and Remove (spam, trash in `--urgent`); each row has a label and a one-line hint in `--text-3`. Informational parts stay on the page (company banner, folder chips, "On your to-do list"). Same dialogs.
- **Mail-check health**: when an account's checks have failed (or not run) for 15 minutes, the feed shows an error banner "Sift can't check <account> since <time> (<reason>). It keeps retrying and catches up on its own." with Open/Details → Accounts; each account card shows "Last checked 2m ago" in `--text-3`, or the failure in `--urgent`. Phone: same banner and line.
- **Images**: remote images load by default (through the image proxy); Settings → Mail has "Load images in mail automatically". With it off, the reader shows the blocked-images banner with Load images.
- **Phone tabs**: Settings → This phone → "Remember where I was in each tab" (off by default): off, a bottom tab always opens at its top.
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
- Top bar: sticky. **"‹ Back" sits above the title on the left** (detail pages: mail, group, rule editor), and the **page's actions are a row directly under the title**, primary first (e.g. "Save rule", "Cancel", "Delete"). Nothing is parked in the far right corner, where it was easy to miss (owner, 2026-10-24). Long forms repeat their actions at the end of the form. Global search arrives with Phase 3.
- Page width: every page, Settings included, uses the same content width (up to 1280px).
- Icons: 18px, 1.6 stroke, rounded caps, `currentColor` (inline SVG sprite in the page).
- **Built app (`web/`, Phase 2c):** React implementation of this layout. It imports `design/shared/tokens.css` and `components.css` directly (one source of truth) and adds `web/src/styles.css` for layout. Differences from the prototype: Search and Senders are not in the sidebar yet (Phase 3); under **Organize** the top-level folders are listed (8 at most, indented, color square + unread count) as **drop targets**: drag any mail row onto one to file it (it highlights with a 12% signal tint). Folder tree rows are draggable onto each other to nest; the tree ends with a dashed "Drop a folder here to move it to the top level" target. Group rows use `.group-row` with a ▤ avatar, "N mails", unread and urgent tags. `.split` (list + detail) stacks to one column below 1180px. The token usage chart always shows 30 day slots ending today (`.usage-chart`: muted stubs for empty days, 45% signal for past days, full signal for today, max 22px wide, date axis below), so one busy day never fills the chart. **Tooltips:** one custom tooltip for the whole web app (`TooltipLayer`, `.tip`): any element with `data-tip` (plain `title` attributes are converted, so the browser's own tooltip never shows) gets a `--surface-2` card with a `--line-2` border, `--r` corners, 12.5px Satoshi, an arrow, after 300 ms on hover or at once on keyboard focus; above the element, flipped below near the top, kept inside the window; multi-line with `
`. Every control carries one. **Paged lists** (feed, silenced, folder view): 30 mails per page, a pager on top and bottom ("Page 2 of 7 · 193 mails" in Clash for the page, Previous/Next ghost buttons), and each row numbered from 1 on every page (`.row .num`, tabular, `--text-3`). Changing a filter returns to page 1. Mobile has no numbers or pages: lists load more as you scroll. Dialogs use a 60% scrim and `--r-xl` corners; a short toast (inverted colors) confirms actions.

- **Floating Write button** (`.fab`): lime, 58px tall, `--r-lg` corners, pen icon + "Write" in 15.5px bold, fixed 28px from the bottom-right corner on every page except the composer, with a soft dark shadow; icon only below 700px. `main` keeps 96px of bottom space so it never hides the last row.
- **AI for this folder** (`.folder-ai`): a collapsible card under the folder's chips, open when the folder has AI settings. Sections separated by `--line` with small uppercase headings (`.fa-h`): category chips + a toggle for timeline mail; sort mode chips (Off / By company / By sender / By your instruction) with an instruction field; "Ask the AI" ghost buttons, an include-subfolders toggle, an optional instruction, and the last five runs with progress ("12 of 40…") and tokens. Rules page shows a **Folder AI rules** card above the rules. Token usage adds two cards side by side: Everyday AI work (one line per kind) and AI tasks you ran (one line per run, tokens right-aligned, tabular).
- **Landing page** (`web/src/pages/Landing.tsx` + `landing.css`, scoped under `.landing`): the prototype in `design/landing/` brought into the app for signed-out visitors: floating blurred nav bar (logo, section links, Sign in ghost, Get started primary), the "Your inbox, sifted." hero with the falling-mail sieve canvas and count-up stats, marquee, the four-step pipeline, a six-card bento (timelines with a "added by you" step, silent-not-lost, folders that sort themselves, read/search/write, every account, 0 tokens for noise), the phone with notifications dropping in, bring-your-own-key, the big closing call to action and footer. All motion stops with reduced motion. The phone app has a landing screen in the same voice: wordmark, the hero in Clash with lime "sifted.", Get started (primary, 52dp) and I have an account (ghost), three stats, five feature cards (lime-tinted icon tile, title, text) and a closing call to action; a 700 ms fade-up that is skipped when the phone's animations are off.
- **Timeline editing:** each timeline item has small Edit and ✕ chips at the right (dimmed until hover). Sections added by hand say "added by you" (and "reminds you"). **+ Add section** (primary) sits first in the timeline's action row, with **Rename** next to it. The section dialog: Stage select, Title, Date and time, a line saying it takes its place by that time, Note, and a Remind me toggle (disabled for past times). To-do rows get an **Edit** chip; the to-do dialog has What, Due (with Clear), Notes and, for new ones, Company.
- **Sign-up:** the sign-in card has a ghost **Create an account** button under Sign in (when the server allows sign-ups); it switches the card to email, password, password again and **Create account**.
- **Writing mail (Phase 4).** A lime **Write** button (pen icon, 50px tall, 15px label, full sidebar width; icon only when collapsed) sits above the nav; `C` opens the composer anywhere. Inbox gets **Outbox** (paper-plane icon). The composer (`/compose`) is one `--surface` card with `--r-lg` corners: rows for From (a `Select` of accounts; fixed text for replies, forwards and drafts with attachments), To / Cc / Bcc (addresses as chips, ✕ to remove, red border when not an address, a suggestion menu of past senders, "Cc Bcc" ghost button on the right), Subject (the growing text field, no border), then the message area (15px Satoshi, 1.65 line height, at least 300px), attachment chips with sizes and "x of 25 MB", and a footer: **Send**, "Send later…" select, "Remind me if no reply" select, Attach…, "✦ Draft with AI" (replies; disabled with the warn-coloured "Add an API key to enable" note without a key), and the save state at the right ("Saved in Gmail drafts"). Send and Discard repeat in the page actions under the title. The AI panel is a dashed `--line-2` box with quick chips and a one-line instruction field. After Send the app returns to where you were and the toast shows "Sending in 10 s…" with an underlined **Undo** action (`.toast-act`). Mail pages show **↩ Reply** (primary), Reply all and Forward first in the toolbar; each open message in a conversation has the same three ghost buttons under it. **Outbox** page: chip tabs Drafts / Scheduled / Follow-ups / Sent by Sift with counts, standard list rows (`.row .who/.subj/.time`), Tags for state (Scheduled in `normal`, Sent/Replied in `ok`, Not sent in `urgent`, reminded in `warn`).

### Mobile (Android, Compose)
- **App size** (Settings → This phone): Small 0.96, Default 1.08, Large 1.18, Larger 1.3 times the system base size, on top of the user's own font-size setting (`UiScale` in `ui/theme/Theme.kt`, stored on the phone, applies at once; the mail view's text zoom follows it).
- Bottom tab bar icons are 25sp with 13sp labels. The floating add buttons (`AddButton`: "+ New", "+ Add", "+ New rule") are at least 56dp tall with a 26sp "+" and 16sp label.
- Rows of buttons that may not fit (account actions, AI key actions) wrap onto a second line; button labels never wrap inside a button.
- **Writing mail (Phase 4):** New mail starts from the floating Write button. The mail screen shows **↩ Reply** (primary) and **↪ Forward** (ghost) side by side above a full-width ghost **Actions…** button (Reply all is in the sheet's "Write" section). Conversation cards (read screen) have Reply / Reply all / Forward text buttons on `--bg-2`. The composer is a scrolling page: From as account chips, To / Cc / Bcc fields that wrap (comma-separated, red outline when an address is wrong), Subject, a message field of at least 10 lines, attachment rows with Remove, "Remind me if no reply" chips, a full-width **Send**, then Send later…, Attach…, ✦ Draft with AI and Discard. The undo window is a full screen: "Sending in N s…", the recipients, a full-width **Undo** and a ghost **Send now**. A draft changed on another device shows a warn banner with **Load that version** / **Keep mine**. Send later is a dialog with three preset cards, a date picker and hour chips. More → **Outbox** has the same four tabs as the web as chips.
- 300×620 reference frame, status bar, app bar (title + icon buttons), content, bottom tab bar (Feed, Deals, To-do, Folders, More).
- Feed rows: sender on the first line (never shortened by tags), the summary or subject (2 lines), then a last line with the category tag, company tag and account name. Account names: labels start with a capital; email addresses are never re-cased (web and phone).
- Timeline: the stage strip uses short whole names (Drive, Register, Test, Interview, Result); the connector line runs from each dot to the next item whatever the item's height.
- Bottom tab bar (drawn by hand, not Material's NavigationBar): 72dp tall on `--bg-2` with a `--line` top border; line icons (the web sidebar's paths: inbox tray, cube, check box, three lines) at 25dp; the active tab gets a 58×32dp block with `--r-sm` corners in 14% lime behind a lime icon, and its 13sp label turns `--text`. Never a pill.
- **Floating Write button** on Feed, Silenced, Search, Folders, a folder, a group, Outbox, More, Accounts and the read screen: lime, 58dp tall, `--r-lg` corners, pen icon + "Write", 18dp from the bottom-right corner above the tab bar. Deals, To-do and Rules keep their own add button in that corner. Lists leave 96dp at the bottom so the last row can scroll clear of it.
- Folder screen: "✦ AI" (or "✦ AI on") chip next to the folder name opens the **AI for this folder** bottom sheet (same three sections as the web). Rules screen lists Folder AI rules in a card at the top. Usage adds Everyday AI work and AI tasks you ran.
- Sign-in screen: ghost **Create an account** button under Sign in when the server allows sign-ups. Before sign-in the app opens on the **landing screen** (see the web Landing entry).
- Timeline: Edit and ✕ text buttons on each item's first line; a full-width **+ Add section** under the timeline. The section dialog uses stage chips, a title field, a day button and a time button (`DateTimeRow`: Material date and time pickers on `--surface`), a note and a Remind me switch. To-do rows have an **Edit** text button; the to-do dialog has the same day/time buttons with Clear, and notes.
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
