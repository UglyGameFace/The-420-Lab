# The 420 Lab | Release status
20 October 2026

## Development milestone
The agreed foundation and Phase 2 feature plan are implemented in the existing main branch of UglyGameFace/The-420-Lab. No new feature branches were created. The Discord application is deployed separately from Dank Shield.

## Implemented
- Source-linked PubMed questions, NIH PubChem compounds, registered ClinicalTrials.gov studies, NIH/NCCIH/CDC/FDA curated guides, and read-only openFDA prescription-cannabinoid reporting data.
- Explicit warnings distinguishing research study design from evidence quality, adverse event mention counts from risk estimates, and legacy strain names from clinical claims.
- Advanced PubMed design filters for indexed systematic reviews, randomized trials, observational research and all designs.
- Attributed 2017 MIT historical strain-name index with roughly 9,500 names. No copied Leafly data, no potency or effect claims.
- Public, persistent, five-button research panel with private answers, advanced research library and restart-safe callbacks.
- Server-manager panel publish, preview, four visual themes, and in-place edits using the original Discord message link. Branding stays with the panel message in Discord, avoiding a new fragile configuration database.
- Process-level privacy-safe health counters, bounded caching, per-member interaction cooldowns, concurrency limits, and periodic logging.
- Weekly scheduled public API smoke checks through GitHub Actions, requiring no Discord secrets.

## Verified
- GitHub Actions Python checks: 47 tests passed on run 39502953828. Both unit tests and syntax checks passed.
- Independent public API smoke run 39502440649: PubMed, PubChem, ClinicalTrials.gov and openFDA returned parsable results.
- Discloud commit status: success on the final documentation code commit 945745ab19863cfc11c7ea20f20c23bf41c541a5.
- User separately reported the original Discord research commands and public panel working before Phase 2 changes.
- Latest repository branch check: main only.

## Important release limitations
- The new Phase 2 buttons and new slash commands have automated registration tests but have not been individually verified in the user's running Discord client. No private bot tokens were accessed.
- Public API smoke tests do not validate the user's Gemini key, Discord installation, future API reliability, or every answer's scientific accuracy.
- Formal clinical evidence certainty grading requires full-study critical appraisal and is not approximated from publication labels; no fabricated scores are displayed.
- Historical strain names are not a reliable predictor of chemistry or effects, and no one should treat the 2017 snapshot as current laboratory data.
- The bot's in-memory cache and telemetry reset after restart; performance under mass public deployment has not been load-tested. GitHub workflow success is not a 24/7 uptime guarantee.

## Maintenance
Weekly GitHub workflow: Live public-source smoke. Discloud process-health logging runs about every 15 minutes while connected. All changes live directly on main. Any failed provider check should be investigated against current official API documentation rather than silently replaced with invented information.

There are no outstanding implementation items in the originally agreed bounded Phase 2 feature scope. Further product enhancements or dedicated independent production certification should be treated as new work.
