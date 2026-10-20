# The 420 Lab 🌿🔬

An independently written, evidence-first Discord bot to educate adults about cannabis, THC, CBD, positive and negative effects, and research limitations. No personal medical advice, regulated goods sales, or purchasing services.

The project was designed after reviewing CannaBot (https://github.com/canna-dev/cannabot), but does not copy its code or third-party Leafly data.

## Commands

- **/askthc question:** Retrieves short PubMed study abstracts and optionally uses Gemini to explain the research cautiously. Citation links are constructed from validated PubMed IDs rather than AI output. Without an AI key, it displays verified research links without claiming to synthesize them.
- **/compound name:** Retrieves PubChem molecular formula, molecular weight and compound page for THC, CBD, CBG, CBN or THCA. Chemistry properties do not prove medical effects.
- **/trials topic:** Finds cannabis study registrations on ClinicalTrials.gov, with explicit warnings that registrations are not proof of efficacy.

Private (ephemeral) responses, per-user cooldowns, concurrent-request limits, short HTTP timeouts, 15-minute in-memory cache, NCBI request pacing below 3 requests/second. No Message Content privileged intent, tracking history, cannabis consumption journals, or user database.

## Setup

1. Create a separate Discord bot on https://discord.com/developers/applications and invite it with bot and applications.commands scopes.
2. Install Python 3.11+ and dependencies: python -m pip install -r requirements.txt
3. Copy .env.example to .env on your development computer. Set DISCORD_TOKEN privately. For instant slash-command sync during testing, set DISCORD_GUILD_ID to your server ID. Do not commit real secrets.
4. Optional conversational synthesis: create a Gemini API key at https://aistudio.google.com/apikey and set GEMINI_API_KEY. Free-tier quotas and model availability may vary. Without it, /askthc links original PubMed sources only. GEMINI_MODEL selects the model.
5. Start: python main.py

**Discloud:** discloud.config sets NAME, TYPE=bot, MAIN=main.py, VERSION=3.11, RAM=256 and AUTORESTART=true. Store keys in private deployment environment variables. Confirm your Discloud plan permits these resources and deploy as a *separate application* from Dank Shield.

## Checks

Run: python -m unittest discover -s tests -v

Syntax: python -m compileall -q main.py lab tests

The regression suite mocks providers. Real Discord OAuth, hosted Discord slash command sync, live NIH APIs and Gemini quotas have not been validated.

## Scientific and medical limitations

PubMed results can be preclinical, observational, underpowered or lack abstracts. AI explanations may make errors even with research context. PubChem covers chemistry, not treatment advice. ClinicalTrials.gov lists registrations even without published results. A paper's existence does not prove a clinical benefit. For life-threatening symptoms such as seizures, chest pain or breathing problems, seek emergency help.

Public API references:
- NCBI E-utilities: https://www.ncbi.nlm.nih.gov/books/NBK25499/
- NCBI usage limits: https://eutilities.github.io/site/API_Key/usageandkey/
- PubChem PUG REST: https://pubchem.ncbi.nlm.nih.gov/docs/pug-rest
- ClinicalTrials.gov Data API: https://clinicaltrials.gov/data-api/api
- Gemini generateContent: https://ai.google.dev/api/generate-content
