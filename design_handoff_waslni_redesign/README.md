# Handoff: Waslni UI Redesign

## Overview
A full redesign of Waslni (Django app "ptah") — a patient-outreach tool where clinic operators upload appointment/marketing CSVs, review each generated message, and open every WhatsApp message individually. The redesign reworks the operator workflow: floating pill navigation, a keyboard-driven send queue with focus mode, a guided 3-step campaign wizard, a template editor with live WhatsApp preview, an admin center, and a session-summary flow.

## About the Design Files
The files in this bundle are **design references created in HTML** — interactive prototypes showing intended look and behavior, not production code to copy directly. The task is to **recreate these designs inside the existing Django codebase** (`ptah/`): Django templates + the existing `assets/css/app.css` / `assets/js` structure, replacing the current sidebar-shell templates. Keep Django template inheritance (`base.html` + blocks) and the existing view/URL structure; this is a re-skin plus workflow rework of the same pages, not a SPA rewrite. Route transitions and queue interactivity are achievable with vanilla JS (the codebase already uses `campaign_workspace.js`); no framework is required, though htmx/Alpine would fit if already acceptable.

## Fidelity
**High-fidelity.** Colors, typography, spacing, radii, and copy are final. Recreate pixel-perfectly.

## Files
- `Waslni Redesign.dc.html` — the redesign prototype (all 12 routes). Templating note: it is an HTML file with `{{ … }}` holes and `<sc-if>`/`<sc-for>` control tags bound to a JS class at the bottom of the file; read the inline `style="…"` attributes as the source of truth for styling, and the `Component` class for behavior/state.
- `Waslni Current UI.dc.html` — faithful recreation of the current product, for before/after reference.
- `assets/app.css` — copy of the current production stylesheet (token reference for the old UI).

## Design Tokens

### Colors
- Page background: `#f2f6f5`; card surface: `#ffffff`; card border: `#dfe8e6`; hairline dividers: `#edf2f1`; muted surface: `#f7f9f9`
- Ink (dark surfaces / primary buttons): `#0d1c19`; headings: `#0d1f1b`; body: `#17312d` / `#24433e`; secondary text: `#58716d`; muted: `#728985`; faint: `#9aaba8`
- Brand teal: `#0b8f7b` (primary actions, active states, progress bars); dark teal: `#086a5f`, `#07584f`; mint accent (on dark): `#5fd6bd`; light teal chip: `#d9f3ed`
- WhatsApp green (send actions): `#177245`; WA header: `#075e54`; WA bubble: `#dcf8c6`; WA chat background: `#efe7dd`
- Status: success bg/fg `#dff5e9`/`#177245`; warning `#fff1cf`/`#9b5d0a`; danger `#fde5e3`/`#a23b3b`; info `#e2edfb`/`#315f9b`
- Input border: `#c6d1cf`; progress track: `#e6eeec`

### Typography
- Display/headings: **Bricolage Grotesque** (Google Fonts), weights 700/800, letter-spacing −0.02em to −0.03em
- Body/UI: **Public Sans**, weights 400–800
- Scale: h1 `clamp(24px, 3.2vw, 34px)` (landing hero up to 60px); section titles 17px/700; card titles 13–14px; body 13–13.5px; meta 11–12px; uppercase kickers 10.5–11.5px, weight 700–750, letter-spacing .07–.08em; metric numerals 34px/800 Bricolage

### Spacing & shape
- Page container: max-width 1200px (admin 1100, profile 900, edit-profile 640, template editor 1000), padding `96px 28px 64px` (top clears the floating nav)
- Radii: cards 16–18px, buttons 10–13px, inputs 11–12px, pills/chips 99px, modals 20–22px, WA bubble `12px 12px 12px 4px` (sender: `12px 12px 4px 12px`)
- Buttons: primary teal `#0b8f7b` with shadow `0 6px 18px rgba(11,143,123,.28)`; dark `#0d1c19`; secondary white + 1px `#c6d1cf` border; WhatsApp `#177245` with shadow `0 6px 16px rgba(23,114,69,.25)`; min-height 44–48px (compact 36–40px)
- Card shadow: none (border-only); floating elements: `0 14px 40px rgba(10,26,23,.32)`; modals: `0 30px 80px rgba(0,0,0,.35)`

### Motion
- Route transitions: each screen animates in with `routeIn` — `opacity 0→1, translateY(14px)→0, scale(.995)→1`, 380ms `cubic-bezier(.2,.8,.2,1)`
- Modals: backdrop fade 200ms + panel `popIn` (translateY(18px), scale .97→1) 320ms same easing
- Nav collapse, progress bars: 300–400ms same easing

## Screens / Views

### 1. Floating navbar (all authenticated screens)
Fixed, top 14px, horizontally centered pill: background `rgba(13,28,25,.92)` + `backdrop-filter: blur(14px)`, 1px border `rgba(255,255,255,.09)`, radius 999px, padding 6px, shadow `0 14px 40px rgba(10,26,23,.32)`.
- Items (icon 16px + label): brand "W" mark (26px, radius 8, teal gradient) + Waslni, divider (1px, `rgba(255,255,255,.12)`), then Overview, Campaigns, Send queue, Admin, Profile, divider, Sign out.
- Item style: 12.5px/700, color `#9fbcb5`, padding `9px 14px`, radius 999px; hover: white text on `rgba(255,255,255,.08)`; active: text `#0d1c19` on mint `#5fd6bd`.
- **Collapse on scroll** (scrollY > 40): labels animate to `max-width: 0; opacity: 0` (320ms) leaving icons only — except the active item, which keeps its label. Expands back at top.
- Mobile (≤760px): pill docks to bottom (bottom 14px), icons-only + active label, horizontal scroll if needed.

### 2. Dashboard (`/`)
- Header: kicker "AL NOOR CLINIC · MONDAY 1 SEP" (teal), h1 "Good morning, Nadia", sub "22 appointments today. 8 patients still haven't received their reminder." Right: dark button "New campaign" (opens wizard) + teal button "Start sending" (bolt icon → queue).
- Metric row: `grid auto-fit minmax(190px,1fr)`. First card is dark (`#0d1c19`, white numeral, mint label "PENDING TODAY") showing live pending count; three white cards: "Sent this session", "Confirmed today" (14 / 22, green numeral), "Templates" (6 +2 pending, amber suffix).
- Main grid `1.6fr / .8fr`:
  - **Active campaigns** panel: rows with title + meta, purpose badge (Appointment info-blue / Marketing warning-amber), progress label + 6px teal progress bar, chevron. Rows link to the queue.
  - Right rail: **Team activity** card (3 operators: 32px round avatar with initial, name + current campaign, sent count in green; idle member greyed) and a teal gradient **Keyboard-first sending** promo card listing shortcuts, button "Try it now".

### 3. Campaigns (`/campaigns/`)
- Header + teal "New campaign" button → opens wizard modal.
- "All campaigns" panel: same row anatomy as dashboard, "12 total" chip.
- "Message templates" section: cards grid (`auto-fill minmax(240px,1fr)`, bg `#f7f9f9`) with name, status badge (Approved green / Pending amber), "purpose · N placeholders" meta, and an **Edit** button per card. Header buttons: "Approval queue" (→ Admin) and dark "+ New template" (→ template editor).

### 4. Campaign wizard (modal over Campaigns)
Modal 560px, radius 22px; 3-segment progress bar (4px bars, teal when reached).
- **Step 1 — Upload:** dashed drop zone (`#f2faf8` bg, 2px dashed `#9fd8cb`), validated-file confirmation row ("cardiology_14aug.csv · 82 rows · validated"), campaign name input.
- **Step 2 — Purpose & template:** two purpose cards (selected: `#eafaf5` bg, 2px `#0b8f7b` border), then approved-template list rows (same selected treatment); only approved templates selectable.
- **Step 3 — Preview & launch:** first row rendered as WA bubble on `#efe7dd` chat background; stat trio (82 recipients / 2 doctors / 0 invalid rows); teal "Launch campaign →" goes straight to the send queue.
- Footer: Back (from step 2), "Continue →" (dark), close ✕.

### 5. Send queue (`/campaigns/<id>/`) — the core screen
- Header: "← Campaigns", campaign title, live counts line ("Message 2 of 8 · 1 sent · 1 skipped · 6 pending"); right: session progress bar (8px, teal gradient fill, animated width), "Export CSV" (secondary), "Focus mode (F)" (dark toggle).
- Filter row: search input (pill, 230px; matches patient/MRN/phone/doctor/department), doctor chips with counts (active: dark bg), divider, status chips All/Pending/Sent/Skipped (active: teal), right-aligned "N shown".
- **Split view** grid `minmax(240px,.65fr) / 1.35fr`:
  - Left: recipient list (max-height 70vh, scroll). Row: name, right-aligned time (pending) or "✓ sent" green / "skipped" red; sub-line doctor · MRN. Selected row: `#eafaf5` bg + 3px teal left border. Done rows at 55% opacity.
  - Right: current-message card — kicker "RECIPIENT · 2 OF 8", patient name (21px Bricolage 800), meta line (MRN · phone · doctor · time), appointment status pill; message as **WA bubble** (`#dcf8c6`, timestamp "10:02 ✓"); action row: big WhatsApp button ("Open WhatsApp ↵", flex-grow), "Edit E", "Skip S" (red text); footer "← prev · next →" + note "Waslni never sends automatically…".
  - Edit mode swaps bubble for a textarea (2px teal border) + Save/Cancel.
- **Focus mode**: hides list, card goes full-width; toggle via button or `F`.
- **Keyboard shortcuts** (ignored while typing or when a modal is open): `Enter` open WhatsApp, `S` skip, `E` edit, `←/→` or `↑/↓` navigate, `F` focus toggle.
- After send/skip, auto-advance to next pending; when none remain → session summary modal.
- **Doctor summaries** section below: cards per doctor (Total/Confirmed/Cancelled mini-stats, summary sentence, green "Share in WhatsApp" button → wa.me link with prefilled text; prototype shows a toast).

### 6. WhatsApp handoff (modal)
Simulates the wa.me handoff: 440px modal styled as a WA chat — header `#075e54` with avatar + name + phone, body `#efe7dd` with the outgoing bubble (right-aligned, `12px 12px 4px 12px`), footer with green "I sent it — mark as sent" + "Back". In production: open `https://wa.me/<phone>?text=<encoded>` in a new tab, set status to `opened`, and offer the mark-as-sent confirmation on return.

### 7. Session summary (modal)
Shown when the filtered queue has no pending items: green check disc, "Queue complete", two stat tiles (sent / skipped), dark "Back to workspace" button.

### 8. Template editor (`/templates/new`, `/templates/<id>/edit`)
Grid `1.15fr / .85fr`:
- Form card: name input, purpose segmented pills, content textarea (min 150px), placeholder-token chips below (`#patient_name #mrn #doctor #department #appointment_date #appointment_time #appointment_status` — monospace, click to append). Save button disabled (grey `#c6d1cf`) until name + content present; saving sets status to Pending and returns to Campaigns with toast "Draft saved — sent for approval".
- Sticky preview aside on WA chat background: bubble with placeholders substituted with sample data (Layla Hassan / 448291 / Dr. Al-Rashid / Cardiology / 14 Aug / 10:30 / Confirmed), `white-space: pre-wrap`.

### 9. Admin center (`/admin-center/`)
Pill tabs: **Template approval** (badge 2) / **Doctors** / **Team** / **Plan** (active tab: dark bg).
- Approval: card per draft — name, "Draft by X · date · purpose", full content in muted block, right column Approve (green) / Reject (red-outline).
- Doctors: table-style rows (grid `1.3fr 1fr 1fr auto`): name, department, WhatsApp number ("Not added" in faint), Edit button. Uppercase 10.5px header row on `#f2f6f5`.
- Team: avatar + name/email, role chip (Owner · Approver in teal chip), presence ("● Online" green / "Away" faint).
- Plan: dark card (plan name, limits, "Active · renews 1 Oct" chip) + usage card with two labelled progress bars (Campaigns 12/40, Seats 3/10) and "Compare plans".

### 10. Profile (`/profile/`) and Edit profile (`/profile/edit/`)
- Profile: grid `.6fr/1.4fr`. Left card: 72px rounded-square gradient avatar with initial, name, email, "Active team member" chip, divider, two stats (214 messages sent / 9 campaigns worked). Right card: "Workspace details" rows (grid `130px 1fr`): Organization, Email, Mobile, Access role chip; "Edit profile" (dark) in header.
- Edit profile: single 640px card — First/Last (2-col), Email, Mobile, Cancel/Save. Saving returns to Profile with toast "Profile updated"; edited values must reflect in profile and avatar initial.

### 11. Public: Landing, Login, Register
- **Landing** (`/`): sticky translucent header (blurred `rgba(242,246,245,.9)`) with brand, "Sign in", dark "Start free". Hero 2-col: chip "Healthcare messaging, made human", h1 up to 60px with "personal follow-up." in teal, sub copy, teal CTA + secondary; check-note "No bulk sender…". Right: dark app mock-up card rotated 1deg showing the send queue. Below: "From spreadsheet to WhatsApp, without losing control." + three numbered cards (01 Upload your CSV / 02 Work the queue / 03 Send it yourself). Footer: © line + tagline.
- **Login/Register** (`/login/`, `/register/`): split layout — left dark `#0d1c19` panel with brand, kicker, headline, sub, 3 numbered steps (mint numbered discs); right `#f2f6f5` centered 400px form. Register adds Organization name field. CTA teal full-width. Cross-links swap the two.

## Interactions & Behavior (summary)
- Nav: active state per route; collapse at scrollY > 40; scroll to top on route change.
- Queue: filters combine (search AND doctor AND status); selection resets to first row on filter change; statuses persist per row (in production: POST to existing message-status endpoints).
- Toasts: bottom-right dark pill with mint check, ~2.6s, `popIn` — used for CSV export, doctor-summary share, profile save, template save.
- All simulated actions (CSV export, wa.me open, approve/reject) map to existing Django endpoints in `rasel/` views.

## State Management
Per-campaign queue state: recipient list with `status ∈ {pending, sent(operator_marked_sent), skipped, opened}`, selected index, doctor/status/search filters, focus-mode boolean (persist in localStorage), session counters (sent/skipped since page load) for the summary modal. Template drafts: name, purpose, content, status (`pending`/`approved`). Wizard: step 1–3, parsed CSV metadata.

## Assets
No image assets. Icons are inline 24×24 SVG strokes (stroke-width ~1.9–2.2, round caps) — copy the `<symbol>` sprite from the prototype head. Fonts from Google Fonts: Bricolage Grotesque, Public Sans.
