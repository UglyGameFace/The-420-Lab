# The Weed Doctor 🌿🔬

An independently written, evidence-first Discord bot to educate adults about cannabis, THC, CBD, positive and negative effects, and research limitations. No personal medical advice, regulated goods sales, or purchasing services.

The project was designed after reviewing CannaBot (https://github.com/canna-dev/cannabot), but does not copy its code or third-party Leafly data.

## Commands

- **/askthc question:** Retrieves short PubMed study abstracts and optionally uses Gemini to explain the research cautiously. Citation links are constructed from validated PubMed IDs rather than AI output. Without an AI key, it displays verified research links without claiming to synthesize them.
- **/compound name:** Retrieves PubChem molecular formula, molecular weight and compound page for THC, CBD, CBG, CBN or THCA. Chemistry properties do not prove medical effects.
- **/trials topic:** Finds cannabis study registrations on ClinicalTrials.gov, with explicit warnings that registrations are not proof of efficacy.

Private (ephemeral) responses, per-user cooldowns, concurrent-request limits, short HTTP timeouts, 15-minute in-memory cache, NCBI request pacing below 3 requests/second. No Message Content privileged intent or cannabis consumption journals. Optional community ratings use pseudonymous hashes; the opt-in Grower Showcase below also stores a contributor-selected public byline and photo submission metadata in local SQLite. **Privacy:** AI-enabled questions and relevant study excerpts are sent to the external Gemini API; do not submit identifiable health details. Google says free-tier inputs may be used to improve its products.

## Setup

1. Create a separate Discord bot on https://discord.com/developers/applications and invite it with bot and applications.commands scopes.
2. Install Python 3.11+ and dependencies: python -m pip install -r requirements.txt
3. Copy .env.example to .env on your development computer. Set DISCORD_TOKEN privately. For instant slash-command sync during testing, set DISCORD_GUILD_ID to your server ID. Do not commit real secrets.
4. Optional conversational synthesis: create a Gemini API key at https://aistudio.google.com/apikey and set GEMINI_API_KEY. Free-tier quotas and model availability may vary. Without it, /askthc links original PubMed sources only. GEMINI_MODEL selects the model (default gemini-3.5-flash-lite, with a supported free tier for eligible accounts).
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


## Public interactive Discord panel

A server manager runs **/labpanel** in the desired text channel to post a public science desk. The bot needs View Channel, Send Messages, Embed Links, and applications.commands. No Administrator permission or Message Content Intent is required. The command enforces **Manage Server** permission at runtime.

The panel stays usable across bot restarts through stable persistent component IDs registered in setup_hook. Any member may press **Ask the Doctor**, **Explore Topics**, **Cannabinoids**, **Find Strains**, **Research Library**, or **Help & Safety**. Topic and molecule pickers, research forms, and registered trial lookup reuse the same three research handlers as the existing slash commands. All query results remain **private** to the member; the public panel does not expose a member's medical questions. A 15-second per-member panel cooldown and the existing shared backend concurrency cap reduce API abuse. Menus timeout after three minutes; members may reopen them from the permanent panel.


## Phase 2: Verified public-health guides and research-design labels

- **/scienceguide topic** opens curated public NIH/NCCIH, CDC and FDA guidance. Topics: cannabis basics, general risks, heart, lungs, prescription medicines and CBD products. These links are maintained in the source allowlist, not AI-generated.
- The existing public panel's **Research Library** menu has **Official NIH / CDC / FDA Guides**. Persistent root buttons have not changed, so an existing posted panel should keep working.
- PubMed citations now include the year and source-indexed publication type when available. Study design is not an evidence quality score, outcome, or proof of benefit.
- AI study context includes indexed design metadata but its instructions prohibit inferring certainty based only on an abstract, title, or publication type.
- Official guidance needs no new API key and doesn't pass a member question to Gemini.

OpenFDA adverse-event analysis, licensed strain information and advanced per-server controls are future slices. Regulatory and public-health guidance may change, so readers should check the linked agency pages.


## FDA safety-report explorer (Phase 2)

- Run **/fdareports medicine** or open **Research Library → FDA Safety Reports** from an already-posted public panel. The root panel ID and buttons are unchanged.
- The app queries aggregate openFDA report terms for four explicitly allowlisted prescription cannabinoid products: Epidiolex, Marinol, Syndros, Cesamet. It does **not** estimate risks for general THC/CBD or retail cannabis.
- The API counts **reaction terms in product-name-matching reports**. These are not side-effect incidence rates. Reports can contain several medicines and reaction terms, can be duplicates, and have not necessarily been confirmed or causally attributed. No relative comparisons, percentages, safety rankings, case histories or individual report data.
- No API key is needed for low-volume use. Optional private **OPENFDA_API_KEY** raises quotas. A bounded cache lasts six hours per product. Do not store keys in GitHub.
- Sources: https://open.fda.gov/apis/drug/event/ and https://www.fda.gov/safety/fda-adverse-event-monitoring-system-aems . See FDA disclaimers before interpreting any report.


## Advanced research, server branding and monitoring

The following features extend the original public panel. Existing root buttons remain persistent; there is no need to republish the panel for new Research Library options.

| Feature | Discord action | Notes |
|---|---|---|
| Historical strain names | /strain | Approx. 9,500 catalog names from a **2017** MIT dataset, attribution in ATTRIBUTIONS.md. No potency/effect claims |
| Advanced PubMed filters | /papers | Filter by PubMed-indexed systematic reviews, RCTs, observational studies or all designs; type does not prove study quality |
| Panel publish/preview | /labpanel | Optional title, intro, theme (forest/mint/violet/slate), and preview; Manage Server required |
| Edit an existing panel | /labpanelupdate | Paste a panel's Copy Message Link in the **same channel**, specify replacement title, intro, theme; Manage Server required; bot needs Read Message History to fetch it |
| Owner-facing process health | /labhealth | Private uptime, guild count, cache size and aggregate call counts; no member IDs or questions retained |
| FDA safety reporting | /fdareports | Preset FDA-approved cannabinoid medicines, reporting frequencies are NOT risk estimates |
| Reviewed public references | /scienceguide | NIH/NCCIH, CDC and FDA curated guidance |

The panel's appearance is stored as its Discord embed. Each server/channel can have different messages and colors without a new database, and existing buttons survive restarts. Updating a panel does not change feature access permissions; member answers remain ephemeral.

**Monitoring:** The bot emits a privacy-safe health heartbeat roughly every 15 minutes. GitHub Actions includes a scheduled, weekly and manually runnable Live public-source smoke workflow that checks PubMed, PubChem, ClinicalTrials.gov and openFDA without bot tokens or Gemini credentials. Workflow success indicates those public interfaces returned parsable responses at check time, NOT constant uptime or medical accuracy.

**Science limitations:** No automated output is a formal GRADE assessment or substitute for reading and critically evaluating full studies. Older catalog strain labels do not predict effects. FDA adverse-event submission counts are not causal or incidence estimates. The optional Gemini model may be wrong; verified source links should be read and users should speak with qualified clinicians about individual care.

**Deployment:** Only DISCORD_TOKEN is essential. GEMINI_API_KEY is optional for synthesized answers, and NCBI_API_KEY and OPENFDA_API_KEY are optional for higher rate limits. Never commit secrets. The packaged strain-name JSON is bundled with the bot and does not require an external API or extra database.


## Quota exhaustion and abuse resistance

The bot uses a shared, fail-closed quota guard:
- All expensive slash commands and panel requests use a shared per-user 10-minute allowance (default 8), per-server hourly allowance (default 80), and anonymous global command limits (default 15/min and 400/UTC day).
- Every outbound Gemini request is checked immediately before calling the model, under global 2/min and 30/UTC-day caps. Public-source API calls are limited separately (45/min, 1200/UTC day) and NCBI requests continue to use pacing.
- Anonymous global counts are updated atomically in a local SQLite ledger. The ledger contains **no user IDs, guild IDs, question text or secrets**. User/server counters are bounded process-local memory.
- Local SQLite counters can survive a simple process restart **if the file is retained**, but may reset when hosting replaces the filesystem during a deployment. Configure LAB_QUOTA_DB_PATH to durable writable storage supported by your provider, and rely on provider-side caps to cover hosting losses. Multi-instance deployment requires a shared persistent store.
- Configuration variables and conservative defaults are in .env.example. Avoid increasing limits until you know your Gemini tier and costs.
- An API key is never included in response messages. Protect your Google API key using provider-side key restrictions. Gemini project-level spend caps have reporting latency and are not instantaneous; configure caps/alerts on the provider account as a separate line of defense. A billing budget alone is not necessarily a hard cap.
- Rejected attempts are not queued for outbound paid calls, and reaching the Gemini cap keeps research paper links available when PubMed quota permits.

This is quota defense, not a guarantee against every denial-of-service technique. Bots connected to many servers or with a shared deployment behind different processes need centralized rate governance.

### Emergency controls

Set `LAB_AI_ENABLED=false` in your private Discloud environment and restart **The Weed Doctor** to completely disable Gemini requests while keeping PubMed paper links available. You may optionally set `LAB_ALLOWED_GUILDS` to comma-separated numeric Discord server IDs to restrict all quota-gated research operations to those servers. When unset, permitted guilds still share the bot-wide budget. Both controls are off/on configuration switches, not a substitute for provider-side spend caps or key rotation.


### Discord-native app-owner quota controls

Run **/labcontrol** as the Discord **application owner**. The private panel shows current limits and anonymous daily usage, offers **Pause / Resume Gemini**, and a dropdown for editing eight bot usage limits. It validates application ownership before opening and before every mutation, not just Manage Server. Admins who are not the application owner cannot alter global limits.

Changes apply to the running process without a restart and are stored in the same SQLite quota database. The values cannot exceed the deployment environment ceilings. Environment-level LAB_AI_ENABLED=false always wins, and if no GEMINI_API_KEY is configured, pressing Resume cannot provision a key.

**Only internal bot request budgets are controllable here.** Google's project billing caps, payment details and official quotas are separate provider-account controls and are not modified or claimed to be synchronized. See https://aistudio.google.com/ for external billing controls.

### Verifying quota settings across deployments

Use the private /labcontrol owner panel or /labhealth to see **Quota storage continuity**. The bot also logs the result on startup.

- **First observed launch:** no earlier continuity marker was found. Host-level persistence is not yet verified.
- **Prior quota ledger found:** metadata survived an earlier process startup.
- **Prior quota ledger found after a code revision:** saved metadata survived a source-code version change.

This check does not prove backup durability or multi-host shared storage. The quota SQLite file is excluded from Git uploads, and provider billing limits remain separate.


## Branding update: The Weed Doctor

The product is now **The Weed Doctor**, formerly **The 420 Lab**. The legacy GitHub repository address, internal Python module names, environment-variable prefixes, old `/lab*` slash command aliases, and `the420lab:panel:v1:*` Discord button IDs stay unchanged for deployment and interaction compatibility. The four brand-forward aliases are `/doctorpanel`, `/doctorpanelupdate`, `/doctorcontrol`, and `/doctorhealth`.

The default public panel and owner dashboard now use The Weed Doctor. Existing default public panel messages are refreshed when their buttons are clicked (where the bot can edit its own messages). Custom-branded panels are not overwritten; a server manager can update one with `/doctorpanelupdate` and the message link. The term *Doctor* is branding, not a claim of being a medical professional.

Discord's application name and bot account username must also be changed by the application owner in the Discord Developer Portal to rename the account itself. These account-level names do not change from a GitHub code deployment.


## Strain lookup: member instructions

Members have **two obvious routes**: type `/straininfo` and fill in the **name** argument (for example, Northern Lights), or press **🌱 Find Strains** directly on the persistent public panel and enter the name in the form. Research Library → Strain Name Reference is an alternative. Idle Grow Op retains its own `/strain` game command, and The Weed Doctor intentionally does not register `/strain` or `/strains`. Results are private and display up to five matches from both the **2017 MIT** and **2026 CC BY 4.0** name catalogs, with source attribution and non-exact spelling suggestions. Neither catalog provides reliable product-specific chemistry or clinical effects.

Existing public panels are automatically upgraded to show the new button after their next interaction, without overwriting custom titles and introductions. The old five button identifiers remain stable and the new sixth button uses a persistent ID.


### Avoiding a game command collision

Idle Grow Op uses the `/strain` game command, so **The Weed Doctor only registers `/straininfo`** for informational lookup. The interactive **🌱 Find Strains** button remains on the public research panel. The Weed Doctor's older `/strain` and `/strains` aliases were retired; these do not affect the separate Idle Grow Op bot. Existing panel custom IDs remain stable.


## Channel panel visibility and pinning

To publish a panel and add it to channel pins, a server manager runs `/doctorpanel pin:true`. Pinning is **optional**: `pin:false` (default) publishes normally. A preview never pins. Existing panels can be pinned or unpinned without changing their branding: use `/doctorpanelupdate message_link:<link> pin:true` or `pin:false`. These commands also work with the legacy `/labpanel` and `/labpanelupdate` aliases.

The bot needs Discord's **Pin Messages** permission (or Manage Messages on versions that require it). A failed pin operation does not delete the panel; its ephemeral confirmation explains the permission problem. Only members with Manage Server may publish or update panels.

**Discord limitation:** Pinning saves a message in Pinned Messages, not in a fixed header above conversation. In active chat it will still scroll away. For permanently obvious navigation, consider a dedicated read-only #start-here or #weed-doctor channel with the pinned panel and a channel topic linking to it. Automatic sticky reposting is intentionally NOT enabled because it would generate spam and API load.

## Name-catalog coverage and provenance (2026 refresh)

The bot now combines historical Kushy 2017 entries with approximately
19,751 additional strain/product names from the licensed CI-Strains-Pro 2026
source (see ATTRIBUTIONS.md). It normalizes spacing and punctuation, uses
published aliases when present, ranks nearest names before long product
listings, and offers labeled approximate spelling suggestions when no
direct match exists. Some newer market names can still be absent.

Source comparison: Cannlytics offers a strains-data API, but using the
live provider requires a Cannlytics API key and confirmation of data usage
rights. OpenTHC publishes a common data model, not an open universal list.
Leafly and other review sites have restrictive reuse terms and must not be
silently scraped into our bot. No user-generated medical effects or product
THC percentages are treated as clinical facts.

## Leafly source support

Commands /leafly and /straininfo, the Find Strains panel button, and
Research Library's Leafly Strain Profiles all provide Leafly references.
Ten individually verified Leafly profile links are available, including
Blue Dream, Super Boof, Northern Lights, Permanent Marker, RS11, Gelato 41,
Animal Face, Runtz, Lemon Cherry Gelato and Wedding Cake. Known aliases
such as Blockberry resolve to the verified primary profile. Unverified
names get a site-restricted external search instead of a fabricated URL.
Search results still include the 2017/2026 locally licensed catalogs.

Optional authorized CSV: Set LEAFLY_LICENSED_CSV_PATH to the path of an
owner-supplied, legitimately licensed Leafly-compatible export. Supported
fields are Strain/Name, Rating, Effects and Flavor/Flavors. If a row matches
a requested name, the bot displays the supplied historical rating and
self-reported effects and flavors with clear uncertainty warnings.
The CSV is not supplied, fetched, or redistributed by this repository.
The import is limited to 16 MiB and at most 100,000 rows.

Why not simply reuse CannaBot's advertised database? The public GitHub
repository canna-dev/cannabot includes a CSV reader but does NOT include
the required data/leafly_strain_data.csv. Nor does it provide a public live
Leafly strain API. Leafly's July 2026 terms restrict automated querying
and mining. The Weed Doctor does not scrape or copy Leafly's proprietary
reviews. Official reference: https://www.leafly.com/strains
Terms: https://www.leafly.com/info/terms-of-use

### Recovered original Leafly CSV: provenance and compatibility

The exact missing CannaBot-compatible CSV was located at:
https://github.com/iboc/cannabis/blob/main/leafly_strain_data.csv
https://github.com/contenthousestudios/canna/blob/main/leafly_strain_data.csv

Both publicly accessible files have the same Git blob SHA
7a3a3a6136efc56f8ebb53b8d183e2c81b0cdf94.
The 2.78 MB CSV parses to exactly 4,762 distinct strain-name records and
64 columns (name, img_url, type, thc_level, most_common_terpene,
description and individual reported-effect percentages). CannaBot's
README advertises exactly 4,762, consistent with these mirrors.

The mirrors contain NO documented grant to reproduce or distribute
Leafly-owned descriptions, media or ratings. Public GitHub availability
is not the same as permission for republishing the file. Under Leafly's
July 2026 terms, automated extraction and unauthorized copying are
restricted (https://www.leafly.com/info/terms-of-use). Therefore the
CSV is NOT bundled, fetched during installation, or loaded automatically.

The private, opt-in CSV adapter now understands the recovered CSV
layout as well as generic CannaBot-style Rating/Effects/Flavor columns.
For effect percentages it displays only top historical labels, not
percentages: the source gives no robust denominators or current
survey dates. It omits the legacy THC number, photo URLs and descriptions.
Only configure LEAFLY_LICENSED_CSV_PATH with data that you are authorized
to incorporate in a publicly accessible bot.

### Activated historical name coverage (2026-10-20)

The Weed Doctor now includes a names-only historical Leafly-mirror supplement
at data/leafly_names_legacy.json, enabled by default. The recovered mirror
contains 4,762 CSV rows and 4,754 normalized distinct names. Of those,
2,298 unique names were missing from our licensed catalogs and are added
as separate name references, yielding 30,582 distinct normalized searchable names overall (some pre-existing aliases and collisions are deduplicated at runtime).

No Discloud environment switch or third-party API key is required for this
name-only lookup. Name-only records are labeled as historical third-party
mirror records, NOT as currently verified official Leafly profiles.
Existing licensed-source entries take precedence for collisions.

IMPORTANT: This is not activation of the full mirrored CSV. Original
descriptions, review prose, images, THC numbers and reported effect
percentages were not incorporated or redistributed. The private CSV
adapter can still read an authorized full copy when supplied. The GitHub
mirror has no license granting reuse of those content fields, and Leafly's
terms prohibit unauthorized redistribution.

## Public strain profiles, database transparency and original ratings

Members can use **/straindb** or the persistent panel's **📊 Database Info**
button to see how many distinct strain names the bot really indexes and the
dates/limitations of its three datasets. It currently indexes **30,582**
distinct normalized names across Kushy (snapshot 2017-11-14), CI-Strains-Pro
(release year 2026), and an old third-party Leafly-name mirror whose actual
collection date is unverified. The app's local index was assembled on
2026-10-20. **Deployments do not automatically refresh any of the datasets**.

Use **/strainprofile name:** to see a richer, credited profile inside Discord:
name/breeder and source, a description and genuine image only when supplied
with reuse authorization, Leafly's original external page (if verified), and
a link to independent lab samples. The **Find Strains** public-panel action
opens the same richer profile.

Additional data sources:
- **Cannlytics Cannabis Results**:
  https://huggingface.co/datasets/cannlytics/cannabis_results
  The published multi-state lab-results archive carries CC BY 4.0 terms,
  with caveats for third-party data. Chemical results represent individual
  samples, NOT the potency/effects of every product sharing a cultivar name.
  The collection is large and is **linked rather than downloaded to Discloud**.
  API access requires a separate Cannlytics token.
- **Wikimedia Commons**:
  https://commons.wikimedia.org/wiki/Special:MediaSearch
  Images are licensed individually, and licensing/name matching must be
  verified before inclusion. Images are not randomly auto-selected.
- **Leafly** original profiles and the historical name-only mirror. Its
  proprietary review content and photos are not licensed to this bot.
- **OpenTHC** https://api.openthc.org/ is a proposed interoperability
  schema for cultivar, product and lab data, **not** a live free strain
  information service.

To supply original/approved descriptions and licensed images across the bot,
the Discord **application owner only** uses
**/doctorstrainset name description source_url rights image_url**.
The bot records the declared rights, source URL and profile update date and
renders them in /strainprofile. A wrong entry can be deleted with
**/doctorstrainclear name**. Do not submit Leafly proprietary material
unless you separately have a valid redistribution license; the rights
selector is a declaration, not a substitute for an actual grant.

For independent first-party scores, a server manager can opt in with
**/strainreviews enabled:true**. Members then use **/strainrate** (1–5),
one updateable score per user per strain per server. Only anonymous aggregates
(count/mean) are shown. Reviews are NOT Leafly reviews or medical evidence.
Managers can disable collection or erase all reviews for their server with
**/strainreviews enabled:false clear:true**. Disabled by default.

Those curated descriptions, image references and original ratings are stored
in a **local SQLite file** (`strain-profiles.sqlite3` by default; override with
`LAB_STRAIN_DB_PATH`). Actual retention after Discloud file replacement is
not verified. Use durable storage and backups when available; the anonymous
source catalogs remain usable even if review storage is lost. No database
records are committed to public GitHub.

## Live and historical strain data controls

See [STRAIN_SOURCES.md](STRAIN_SOURCES.md) for current source terms, data
quality, photos and lab chemistry limitations, privacy controls and freshness.

Public `/straindb` and the **📊 Database Info** panel button show the
**actual deduplicated local index size** plus each source's snapshot date.
The database is compiled from Kushy 2017, CI-Strains-Pro 2026 and a historic
Leafly-name mirror. It **does not automatically sync Leafly reviews**.

`/strainprofile name:` combines locally indexed names, credited and
permission-cleared descriptions/photos (if supplied), optional original
community ratings from this server, and an on-demand **CannaLib** educational
source lookup. CannaLib requests are read-only, never cached, strictly
rate-limited to 35/hour and 180/day, and carry the required visible credit.
No account or configuration is necessary for anonymous access, but its
availability is not guaranteed. Optional `CANNALIB_ENABLED=false` stops the
external queries. Optional `CANNALIB_API_KEY` may be supplied privately to
use an authorized provider account. Data is not copied into our catalog,
resold or used to train AI models. Consult https://cannalib.org/api/terms/.

The app owner can use `/doctorstrainset` and `/doctorstrainclear` to
manage descriptions and original/licensed photos with source attribution.
Server managers may **opt into independent server reviews** via
`/strainreviews enabled:true`; members then use `/strainrate`.
No Leafly proprietary reviews are reproduced. The separate
`strain-profiles.sqlite3` storage file may be lost on hosting redeploy if
persistent disk is not configured; deployment status does not prove retention.


## Profile source fallback and real database counts

Use /straindb or the public Database Info button for the exact offline strain-name count, source releases and freshness warnings. Server managers can publish this status using /straindb public:true. Use /strainprofile for enriched, credited cultivar context. The bot now tries CannaLib, then the publicly documented StrainAPI v1 API on an exact-match basis. See https://www.strainapi.com/api-terms/ for attribution and developer-use permission. Live provider results are not merged into the offline catalog count, and third-party images are not embedded without licensing. Real cannabinoid and terpene test values must be linked to a specific laboratory batch; the Cannlytics public dataset is linked as an independent batch-specific research source.

## Sources, rights, statistics and lab results (public Discord UX)

Use /straindb to view the actual offline strain-name total and source dates.
Managers may set public:true to publish that card in a server channel.
The persistent public panel includes a Database Info button and visible
catalog count. Research Library now offers Data Sources, Photos & Lab
Results. The same comparison is available using /strainsources; managers
may set public:true to publish the source guide for everyone.

Connected on-demand: CannaLib attributed strain claims (with shared rate
budgets and no long-term response cache), followed by documented StrainAPI
exact-name records if CannaLib cannot confirm a match. These supplement
/strainprofile, but are not counted as local stored strains. Read and
obey each provider's API licence and usage limits before commercial scaling.

Independent external dataset: Cannlytics cannabis_results, a CC BY 4.0
collection of laboratory results and COAs from multiple states, is linked
as an external batch-specific research source. Do not treat measurements
from one sample as the universal potency for all products with that name.
An authenticated Cannlytics API account is needed to use its managed API;
the bot does not claim a free universal query endpoint.

Pictures: Wikimedia Commons has individually licensed images, not
guaranteed photos of a specific cultivar. The app owner can contribute
original or independently licensed descriptions/images using
/doctorstrainset with explicit source and rights. Server managers can
opt into first-party, per-server original ratings using /strainreviews.
These scores are NOT Leafly ratings. The full Leafly review library,
copyrighted descriptions and images are NOT reproduced or claimed live.

Dataset snapshots: Kushy 2017-11-14, CI-Strains-Pro 2026, undated
historical Leafly-name supplement. Provider lookup freshness does not
mean these packaged files automatically update on a schedule.


## Independently sourced short strain descriptions (2026-10-20)

The /strainprofile command now uses the read-only Flower & Freedom beta API before its existing CannaLib and StrainAPI fallback. Where an exact name matches, it displays a short original provider summary, reported genetics, aromas and effects, the upstream profile URL, and its actual source update date. It never converts a single product's lab test into an estimate for all products of that strain. The API currently advertises about 50 profiles and requires visible attribution, which is included. Only requested records are fetched, with a short bounded in-memory cache; no bulk mirroring and no new credentials. Toggle with FLOWER_FREEDOM_ENABLED=false if necessary. The existing /straindb database-size count includes **only packaged local name indexes**, not these 50 remote provider profiles, so the count remains accurate. The public source guide /strainsources also distinguishes these independently owned summaries from unlicensed Leafly descriptions and images.

Other alternatives: Find My Seeds publishes a read-only strain API with community scores, review counts, and image fields, but individual third-party image rights still require verification before embedding; Strainpedia's private developer API advertises structured images and effect descriptions at $50/month. Neither option should be represented as a live Leafly data feed.

## Independent rich profiles now live

The public Find Strains modal and /strainprofile share the same credited
profile builder. They include current source-reported details when a free
external provider responds, without changing the packaged name count.
Provider order: Flower & Freedom original summaries, Find My Seeds
community descriptions and ratings, then CannaLib and StrainAPI.
Find My Seeds uses its free exact-name public API with one-hour caching
and per-bot quota protections. Its score is always labeled as a
Find My Seeds community rating, never a Leafly score, efficacy claim,
or independent lab measurement. Source photos are accessible through
the provider's original profile link, rather than copied into our bot.
The existing private /doctorstrainset supports photos you own or have
permission to publish. Use FINDMYSEEDS_ENABLED=false to disable the
new external provider if it becomes unavailable.
Source: https://www.findmyseeds.com/find-my-seeds-public-api/

## Credited real flower photos and optional Cannlytics

**Available with no setup:** Named Weed Doctor strain cards now omit
any unverified photo, rather than attaching one generic cannabis image to
unrelated cultivars. Members may view original source profiles; attributed
owner-supplied pictures appear only if explicitly provided for the exact name.

**Generic pictures:** Wikimedia Commons and the optional Pexels helper can
provide credited cannabis-flower illustrations for non-cultivar materials,
but these photos are no longer inserted into named strain profiles. Even a
beautiful bud photograph cannot authenticate a strain by appearance alone.

**Optional Cannlytics:** Add CANNLYTICS_API_KEY privately to enable
read-only, exact-name requests to the documented
https://cannlytics.com/api/data/strains/ endpoint. Results are bounded
and cached for 1 hour, never treated as potency predictions for a
particular product. No API call is made without an authorized key.

References: https://commons.wikimedia.org/wiki/File:CannabisBud.jpg
https://www.pexels.com/api/documentation/
https://docs.cannlytics.com/api/data/strains/

Live Pexels and Cannlytics calls have not been verified in the owner
deployment because their respective secret API keys are not connected.
Generic photo fallback is disabled for all named strain cards.


### Corrected strain profiles: photo and identity accuracy

The Weed Doctor does **not** attach generic Wikimedia Commons / Pexels bud
photos to named strains anymore. Only owner-supplied, source-credited imagery
is eligible for the named profile, marked as owner-submitted identification.
Unverified strain photos are omitted rather than mislabelled. External named
strain pages are linked for viewing their own photographs.

Strain classification, lineage, and breeder listings are source-specific,
not guarantees of the genetics a particular member owns. The Northern Lights
profile now distinguishes Leafly / Sensi Seeds indica references from the
historical Kushy Hybrid label and the CI commercial breeder listing. Missing
remote providers are collapsed into a single neutral status, not shown as
research facts.


### Source-attributed cultivar photography

The first vetted cultivar-labelled image is **Northern Lights**, a 2007 photo credited to User Dan on Wikimedia Commons, licensed CC BY-SA 3.0:
https://commons.wikimedia.org/wiki/File:Northern-lights-flowering.jpg
The source identifies the pictured plant as Northern Lights; its genetics and any reader's batch are not independently verified. The bot shows this image only for an **exact Northern Lights** lookup. Other strains without an original owner-curated or comparably documented photo display **no image** rather than a generic bud. Existing Pexels fallback utilities are no longer called by the profile path.


## 🌱 Grower Showcase (opt-in, server-only)

This is a real feature for growers, not a crowdsourced shortcut to building a
global image library. Contributors can document their plants with **original
photos**, keep an **approved grow-stage journal**, and earn **server-local
contribution milestones**. It does not provide cultivation instructions,
medical predictions, cannabis sales, seeds, or purchasing services.

**Manager setup:** Run `/growerconfig` to choose two separate age-restricted
text channels: a *private staff-review* channel not viewable by @everyone and
a *gallery* channel. The bot needs View Channel, Send Messages, Attach Files,
Embed Links and Read Message History in both. Server managers can pause new
uploads by running `/growerconfig` again with `enabled:false` and the same
channels. Existing approved photos and owners' withdrawal rights remain.
Members cannot post directly into the gallery through this feature.

**Contributor workflow:**
- `/growersubmit` accepts an original JPEG, PNG or WebP photo (8 MiB maximum),
  an **exact catalog strain name**, a reported growth stage, optional progress
  notes and explicit permission to show the image **in this server only**.
  Photo metadata, including EXIF/GPS, is stripped by re-encoding before it
  reaches the private review channel; file size, pixel count and supported
  formats are bounded. The photo itself might still show private information.
- `/growerprofile` shows approved photos, pending submissions, documented
  strains and milestones at 1, 5 and 20 accepted photos. Progress is private
  by default, with `public:true` for voluntary sharing.
- `/growerjournal` shows up to 12 linked, approved progress photos with
  reported growth stages, dates and captions. Optional `strain:` filters to
  one catalog name and `public:true` lets a grower share their own journal
  in an age-restricted text channel.
- `/growerwithdraw id:` removes the contributor's private submission copy,
  any public gallery copy and the stored entry. The submit confirmation
  includes the ID, and private `/growerprofile` can recover recent IDs. Images remain in Discord's
  own storage only for as long as their messages exist, subject to Discord's
  data handling and caches.

**Restart safety:** Photo submissions now reserve a permanent submission ID
in SQLite **before sending the image to Discord**. The private review photo
includes an upload-ID marker. A lost Discord acknowledgment or bot crash leaves
an `uploading` reservation rather than an untracked image. The affected
contributor must **not reupload** until staff reconcile the reservation.

If an upload, approval or deletion is interrupted for more than five minutes,
`/growerqueue` lists it. Managers run `/growerrecover id:` to inspect the
original review/gallery channel for its bot-authored ID marker and attach the
existing message to the saved record. The bot does not blindly repost.
For unmatched uploads, staff must check the **entire original review channel**
before using `/growerrecover id: confirmed_not_published:true` to clear the
reservation. For unmatched approvals, the same option returns the submission
to the private review queue only after confirming no published gallery copy
exists. The automatic scan checks up to 250 recent messages, which is not
proof that an earlier post is absent. Stalled removals can be retried without
reposting an image.

**Moderation:** `/growerqueue` gives managers pending photo IDs and private
review links. `/growerreview id: approve:true/false` publishes the sanitized
copy or rejects/deletes the pending copy. `/growerremove id:` lets managers
remove pending or published contributions. Approvals are serialized through
the SQLite submission state so concurrent clicks cannot intentionally publish
twice. A process crash between Discord publishing and database confirmation
can still require manual reconciliation.

**Privacy and reuse:** Only authorized reviewers see pending photos. After
approval, a contributor's **current submission-time display name**, caption,
image and claimed strain/stage become visible to viewers of the chosen gallery.
Submission identity is saved as a salted per-server hash, not a raw Discord
member ID. The app does not prove plant genetics or the photographer's
ownership. Photos are **not automatically imported** into global
`/strainprofile` records or offered for reuse outside that server. The
manager should moderate labels, permissions, imagery, and local law.

**Storage limitation:** Gallery and review images live in Discord channel
posts; submission states and contributor stats share the existing
`LAB_STRAIN_DB_PATH` SQLite file. **Persistent disk and a backup** are
required to preserve indices, journal links, moderation status and user
withdrawal mapping after a Discloud redeployment. This storage durability has
not been validated in the live hosting environment. Multiple independent bot
instances must use coordinated/shared persistence instead of distinct SQLite
files. No uploaded photos or database records are committed to GitHub.
