# Active task: The 420 Lab evidence-first Discord bot

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
