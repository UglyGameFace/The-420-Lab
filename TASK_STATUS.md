# Active task: The Weed Doctor (formerly The 420 Lab) evidence-first Discord bot

**CURRENT STATUS (20 October 2026): The planned Phase 2 feature set is implemented on main. Live and unit verification details are in RELEASE_STATUS.md. Earlier notes below are historical and may list work that is now finished.**


## Outcome and scope
Build a separate, low-cost Discord THC/cannabis education bot using reputable scientific databases, with both potential benefits and adverse effects represented objectively. Keep it separate from Dank Shield and do not copy CannaBot's bundled Leafly data.

## Status
- Initial foundation implemented on main and deployed via Discloud. User reports the bot is installed in their Discord server, its slash commands are visible, and the command test(s) worked. Specific command outputs and logs have not been independently inspected.
- Commands: /askthc, /compound, /trials.
- Backends: PubMed E-utilities (article search and XML abstracts), NIH PubChem chemistry, ClinicalTrials.gov registrations.
- Optional Gemini 3.5 Flash-Lite synthesis only when configured. Research-link fallback works without AI credentials.
- Every public research link is generated from provider identifiers. Model-generated URLs are suppressed.

## Root findings / actual path
- New repository was empty, so there was no existing execution path to preserve.
- Reviewed canna-dev/cannabot: the active bot was a consumption tracker, not a working public conversational science bot; inconsistent bioavailability rates appeared in code.
- Entry point main.py -> lab.bot (discord.py app command handlers) -> lab.sources (read-only NIH/trial adapters) -> lab.answers (optional model synthesis and verified links).
- Configuration: DISCORD_TOKEN, optional DISCORD_GUILD_ID, GEMINI_API_KEY, GEMINI_MODEL, NCBI_API_KEY. Discloud entrypoint in discloud.config.

## Changes and validations
- Source adapters include NCBI pacing, 15-minute bounded in-memory cache, bounded query/results, HTTP timeout and provider errors.
- Discord responses are private, with per-user cooldowns, bounded concurrency and no message-content privileged intent.
- Test workflow: .github/workflows/tests.yml (unittest and compileall).
- 13 local unit tests passed on an updated, closely equivalent working copy using mocked public API responses. One Discord command-registry test was skipped locally because discord.py was unavailable; it remains enabled in CI after dependencies install. Tests cover source error handling, CBD-focused search, parsing, caching, URL safety and disclaimers.
- Static compilation passed on the updated working copy.
- Fixed stale footer assertion after privacy wording changed; added CBD-relevance regression test and startup gateway-ready log.
- An earlier Discloud commit status reported success. The user subsequently confirmed that the bot appeared in their server with slash commands and the tested functionality worked.
- **Remote GitHub Actions results were not independently confirmed**; connector's commit workflow lookup reports PR-triggered runs only, and combined status returned no status contexts.
- User-reported live Discord responses are successful; the specific three individual command results and underlying source/model outputs have not been independently verified. Gateway logs, Gemini quota, source response quality, failure paths and long-running hosting remain unverified.

## Cleanup / conflicts
- Only main was found in repository branch search; no temporary feature branches were created.
- The repo is newly initialized and contains no user work to overwrite.
- No CannaBot source or third-party dataset was imported, avoiding conflicting THC estimates and third-party asset licensing.

## Blockers and next step
- User reports configuring environment variables on Discloud; do not request or print credential values. The bot responds in Discord; deployed SHA, gateway logs and sustained runtime health remain to be checked.
- Inspect GitHub Actions after the latest main commit; this environment cannot retrieve push-run conclusions via the connected GitHub workflow tool.
- Confirm Discloud logs contain `Commands synced; AI configured: True` (if Gemini configured) and `Discord gateway ready`.
- User reports a successful live test following the three-command checklist. Confirm each command's output and citations at least once; capture error types/status only, never secrets or identifiable health details.
- User-observed Discord commands are working; independent API accuracy and production stability remain to be established. Fix any live provider issue before wider rollout.

## Backlog (same project; not concurrently active)
- Add openFDA medication labeling/adverse-event context with warnings about spontaneous-report bias.
- Add medically reviewed NCCIH/CDC/FDA guidance and study-quality labels (systematic reviews, clinical trials, observational/preclinical).
- Evaluate licensed and current cannabis strain data independently before importing anything.
- Add long-term operational metrics and abuse controls after runtime traffic is measured.


## Current active extension: public panel

The user confirmed all three research commands work in Discord. Added a public, persistent Discord science panel with five buttons and private research menus. Publish with /labpanel (Manage Server permission required); member interactions reuse the existing authoritative research handlers. Validations for the new panel include command registry, persistent button IDs, publish permissions and panel cooldown. GitHub Actions run 39496579543 succeeded with 17/17 tests plus syntax checks. Discloud commit status succeeded on code commit 03530d1ead0c587d2e6b5c1aad60aaffc0dbd69e. Changed files were confined to panel, shared bot handlers, tests and documentation. Only main exists. Live panel publication and individual button interactions remain unverified; run /labpanel once and test buttons and private replies after deploy.

## Follow-up: new /labpanel command not visible (2026-10-20)

The user sees the three previous research commands but not the panel publishing slash command. The code registers four commands. Root issue identified in command-sync scope: when DISCORD_GUILD_ID was set, startup synchronized *only* that guild and skipped global synchronization, risking stale commands in other guilds. The /labpanel command also has Discord's default Manage Server visibility restriction, so non-managers cannot see it; its server-side permission guard is retained. Changed sync behavior to always publish global commands then refresh an optionally configured guild and log/verify each returned command name. Added regression tests for global+guild, global-only, and missing-command detection. Validate GitHub Actions and Discloud deployment, then verify /labpanel is visible to an account with Manage Server permission and post/test the persistent panel. Live visibility still unconfirmed.


## Phase 2 science-quality slice: 2026-10-20

Implemented scienceguide slash command plus curated NIH/NCCIH, CDC and FDA official reference links. The existing public panel's Research Library menu now offers Official NIH / CDC / FDA Guides without changing persistent root button identifiers or requiring reposting.

PubMed answers display publication year and PubMed-indexed study design metadata when available. They explicitly warn that indexing does not establish evidence quality, clinical benefits or causation; AI instructions now reflect this restriction.

GitHub Actions run 39499656701 passed 26 tests and syntax checks, including guide source allowlists, the picker and publication metadata. Subsequent documentation-only updates need their own Discloud status verification. User has not yet tested the new scienceguide or expanded Library menu in Discord.

Future slices: FDA adverse-event reporting analysis with reporting-bias safeguards, additional study-methodology context, licensed strain database evaluation, optional per-server panel controls. Do not claim these are implemented. No new branches were created.


## Phase 2 slice: FDA adverse-event reporting

Implemented an openFDA reporting explorer for only FDA-approved cannabinoid medicines, with choices Epidiolex, Marinol, Syndros and Cesamet. The new /fdareports command and the existing public panel's Research Library menu share the same read-only request handling. Displayed counts are report reaction-term mentions, explicitly not causal incidence or comparative risk. Individual adverse event cases, patient details and unapproved retail cannabis are excluded. Six-hour bounded cache and optional OPENFDA_API_KEY reduce quota use. Added tests for allowlist enforcement, 404/429 handling, sanitization, caching and menu integration. Live API response accuracy and post-deploy menu behavior remain pending verification. Avoid broadening to unsupported side-effect claims or numeric safety scores.


## Abuse and budget hardening

Reviewed request paths after the user's concern that alternate accounts could burn paid AI tokens. Found independent slash versus panel cooldowns, no per-guild limits and no bot-wide Gemini allowance. Added a shared interaction admission guard, anonymous transactional global budgets in SQLite, per-user/guild process limits and provider-specific pre-flight caps. The quota ledger stores no user IDs or question content. Source queries and Gemini calls fail closed if quota storage is unavailable. These controls require live deployment and testing; filesystem persistence cannot be assumed after Discloud redeploys. Provider-side caps and key restrictions remain independently important. See README for settings.

Additional abuse controls: added optional LAB_AI_ENABLED=false emergency cutoff and LAB_ALLOWED_GUILDS comma-separated allowlist to restrict costly research to approved servers. No guilds are hard-coded by default, preserving public multi-server use.

2026-10-20 owner usability extension: added Discord app-owner-only `/labcontrol` with pause/resume Gemini, live lowerable quota caps and anonymous usage counters. Settings survive process restart if SQLite data persists and never override deployment ceilings. Google billing controls remain external and require Google account authorization.

## Ledger continuity release follow-up

Added boot-level SQLite continuity markers, startup diagnostics and /labcontrol and /labhealth visibility. A fresh-interpreter integration test confirms persisted AI pause, lowered Gemini cap and consumed quota remain enforceable when the same database is retained. CI passed all 68 tests; GitHub deployment integration reported Discloud success. Real Discloud filesystem retention cannot be established from currently connected tools and remains unverified. No extra branches or credentials required.


## Current active rebrand: The Weed Doctor

User requested rebranding from The 420 Lab to The Weed Doctor. Discord-visible titles, panels, help messages, owner controls, system prompt, Discloud display name and primary documentation were renamed. Four brand-forward command aliases were added while retaining old slash commands and stable persistent panel custom IDs for backward compatibility. Default older posted panels update on their next interaction, without overwriting server-custom titles. The legacy GitHub repo slug and internal module/config identifiers remain for deployment safety. Discord app name and bot username still require an authorized Developer Portal rename; code cannot establish that update.


## Strain discoverability fix

User reported strain discovery and instructions were unclear. Added a prominent 🌱 Find Strains root button on the public panel (six total); a self-explanatory `/strains name` alias to the existing `/strain` handler; explicit example Northern Lights in modal, panel embed, help text and README. Legacy public panels upgrade their view after the next button interaction without overwriting server-custom titles. Kept old button identifiers, per-user quota admission and ephemeral answers intact. Validate GitHub Actions, Discloud and live Discord UI; actual live interaction not yet inspected.


## Command name collision correction

The owner reported Idle Grow Op already owns `/strain` for gameplay. To avoid clashing with their game bot, removed The Weed Doctor `/strain` and `/strains` commands and registered only `/straininfo name` for the historical strain reference. Updated onboarding, embed, help, tests and documentation. Preserved the public 🌱 Find Strains panel button and its stable custom ID `the420lab:panel:v1:strain`. Fixed an inadvertently un-awaited async test by moving it into an `IsolatedAsyncioTestCase`. Verify global Discord sync, CI and Discloud deployment; the original Idle Grow Op application is untouched.

## Channel panel pinning option (2026-10-20)

Added optional per-panel `pin` flag to /doctorpanel, /labpanel, /doctorpanelupdate and /labpanelupdate. New panels default to unpinned; managers can opt in. Existing panel pin changes preserve the embed if no style parameters were supplied, so channel-specific branding is not overwritten. The bot requires Discord Pin Messages permission or equivalent, catches pin/unpin failures, and keeps existing persistent component IDs. No automatic repost/sticky mode was added, as Discord pins do not float above chat messages and reposting would cause noise and rate-limit risk.

## Leafly reference integration

The user requested Leafly integration based on canna-dev/cannabot.
Inspection showed that CannaBot ships a parser for
data/leafly_strain_data.csv, but the public GitHub repo does not contain
the CSV or a working public live Leafly strain API. Leafly's terms restrict
automated extraction. Implemented verified individual profile references
for ten well-known names and aliases, explicit search fallbacks with no
fabricated profile claims, /leafly command, /straininfo companion references,
Find Strains panel behavior, and Research Library Leafly category.
Added optional private Leafly-compatible CSV import via
LEAFLY_LICENSED_CSV_PATH for appropriately authorized data. The code does
not bundle or retrieve a copyrighted Leafly dataset. Protects against
untrusted input, overlarge files, and misleading medical conclusions.
Automated tests cover known links, aliases, unverified names, invalid
inputs, and authorized CSV parser behavior. Still requires a live Discord
member test; no live Leafly data feed is authorized or activated.
