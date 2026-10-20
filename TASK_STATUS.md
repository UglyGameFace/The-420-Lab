# Active task: The 420 Lab evidence-first Discord bot

## Outcome and scope
Build a separate, low-cost Discord THC/cannabis education bot using reputable scientific databases, with both potential benefits and adverse effects represented objectively. Keep it separate from Dank Shield and do not copy CannaBot's bundled Leafly data.

## Status
- Initial foundation implemented on main; not yet validated in a real Discord guild or Discloud runtime.
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
- 12 local unit tests passed on a closely equivalent working copy using mocked public API responses, including empty/error inputs, identifier validation, caching, missing AI, link handling and long-answer bounds.
- Static compilation passed on the working copy.
- **Remote GitHub Actions results were not independently confirmed**; connector's commit workflow lookup reports PR-triggered runs only, and combined status returned no status contexts.
- Live Discord sync, Gemini output/quota, PubChem name resolution, ClinicalTrials.gov matching, PubMed service behavior from Discloud and hosting startup remain untested.

## Cleanup / conflicts
- Only main was found in repository branch search; no temporary feature branches were created.
- The repo is newly initialized and contains no user work to overwrite.
- No CannaBot source or third-party dataset was imported, avoiding conflicting THC estimates and third-party asset licensing.

## Blockers and next step
- Needs a private Discord bot token to run, and a hosting configuration. For AI conversational summaries, a private Gemini API key is required.
- First perform GitHub Actions check, then configure bot credentials privately, register commands in a test server, and test the three commands using real upstream responses. Inspect errors and correct issues before any public rollout.

## Backlog (same project; not concurrently active)
- Add openFDA medication labeling/adverse-event context with warnings about spontaneous-report bias.
- Add medically reviewed NCCIH/CDC/FDA guidance and study-quality labels (systematic reviews, clinical trials, observational/preclinical).
- Evaluate licensed and current cannabis strain data independently before importing anything.
- Add long-term operational metrics and abuse controls after runtime traffic is measured.
