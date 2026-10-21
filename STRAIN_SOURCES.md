# The Weed Doctor: strain information sources

Last checked: 20 October 2026. The numbers below are separate source categories
and must NEVER be added together to inflate our in-bot catalog size.

## Data already available in Discord

- /straindb and the public Database Info button: compute local index size
  dynamically; currently 30,582 unique normalized name entries.
- Kushy MIT snapshot: 9,508 catalog rows; 14 November 2017.
- CI-Strains-Pro CC BY 4.0: 19,751 selected 2026 rows, with attribution.
- Historical Leafly-name mirror: 2,298 supplemental names; original content
  dates are not reliably verified. Leafly did not license the reviews here.
- /strainprofile: local identity and breeder, credited optional descriptions
  and images, optional per-server aggregate member scores, plus an on-demand
  CannaLib mini-profile if its API responds with an exact name match.
- /leafly and /straininfo: existing verified Leafly profile references and
  safe search fallback for names not yet verified on the Leafly site.

## Live external alternative: CannaLib

Site: https://cannalib.org
Read-only API reference: https://cannalib.org/api/
Terms: https://cannalib.org/api/terms/

The bot requests only one user's query at a time and selects up to three
candidate cards, displaying facts only on an exact name match. It does not
import, cache or bulk copy API records. It labels CannaLib data with the
required attribution link Data by CannaLib -> https://cannalib.org.
Free unkeyed account allowance published as 60 requests/hour and 300/day;
our hard SQLite safeguard restricts this bot to 35/hour and 180/day.
Optional CANNALIB_API_KEY may increase provider limits, but bot caps remain
conservative. CANNALIB_ENABLED=false disables provider calls. Free-tier
API data may not be stored beyond the display session; no competing
database, training dataset, or raw API proxy is permitted.

Source chemistry and lineage are **claims with provenance**, not proof of
what a specific purchased or consumed batch contains. Photos exposed on
CannaLib may have third-party copyright issues; the bot does not embed them.
The provider's runtime response and Discord appearance have not been
independently verified against live Discloud; mocked API tests are passing.

## Laboratory evidence: Cannlytics

API: https://cannlytics.com/api
API specification: https://docs.cannlytics.com/api/data/coas/
Open dataset: https://huggingface.co/datasets/cannlytics/cannabis_results
License: CC BY 4.0 with a third-party rights caveat.

Cannlytics provides batch-specific cannabinoid/terpene certificates of
analysis (CoAs), and a separate predictions API for aromas and effects.
CoAs are the preferred evidence when a person has the actual product test;
they cannot establish a universal THC potency for an entire strain name.
Authenticated APIs generally require an account/API key. The bot currently
links to the lab data source; it does not claim to have ingested those COAs.

## Botanical identity & licensed imagery

- Wikidata structured records: CC0, https://www.wikidata.org, but incomplete
  cultivar coverage and limited review statistics.
- Wikimedia Commons: https://commons.wikimedia.org (each image's license
  must be checked independently, with attribution when required).
- CC BY dataset https://github.com/Shannon-Goddard/ci-strains-pro
  offers botanical identity, breeder and lineage information; the bot
  does not blindly republish third-party seed-shop photographs or prose.
- Leafly https://www.leafly.com/strains is a strong community-feedback
  destination, but its review texts/images and claimed THC values cannot
  be republished wholesale without a suitable licence.

## Permission-cleared rich profiles

The application owner may provide a 15–550-character original or properly
licensed description, public attribution URL and optional licensed image
using /doctorstrainset. Only the application owner may mutate globally
curated profiles, or clear them with /doctorstrainclear.

Server managers can optionally enable first-party member ratings with
/strainreviews enabled:true; members use /strainrate.
Those are local user opinions, not copied Leafly scores and not clinical
benefit evidence. The persistent SQLite file is configurable with
LAB_STRAIN_DB_PATH. Its actual retention across Discloud redeploys must
be independently verified; GitHub deployment status cannot prove it.

## Provenance rule

Do not claim a source field exists unless that source returned it. Label
source dates separately from today's bot release date. Never turn missing
chemistry into zero or predicted effects into clinical facts.


## StrainAPI backup for richer strain profiles

Source: https://www.strainapi.com/docs/
Terms: https://www.strainapi.com/api-terms/

StrainAPI permits attributed developer-app usage and offers no-key read-only V1 search and strain details. In October 2026 its website listed about 268 profiles. The Weed Doctor now uses it as an exact-name fallback when CannaLib has no usable profile. It provides source-reported lineage, breeder, terpene, aroma and flavor facts with an original-page link. All external requests count against the bot's existing provider quota. It does not bulk copy the provider, embed third-party images, or assume strain-wide potency. The live profile count is separate from the offline name index. Set STRAINAPI_ENABLED=false to turn it off; provider behavior on Discloud has not been inspected directly.

## Find My Seeds public community profiles

Endpoint: https://www.findmyseeds.com/wp-json/strain-compass/v1/strains
Docs: https://www.findmyseeds.com/find-my-seeds-public-api/
Read-only, no key. The Weed Doctor queries one exact name per user
request and stores at most 128 1-hour memory-cache entries.
Returns per-source excerpt, breeder, reported effects/flavors/terpenes
and community rating + rating_count where available. Never label
these ratings as Leafly reviews or laboratory efficacy.
Source photos are linked through the original page. No bulk mirroring
or copied image hosting. The fallback has a conservative 8-second
timeout and uses the same global research-API safety allowance.
The public Find Strains modal and /strainprofile use the same rich
profile presentation. The local index size in /straindb never counts
remote results as newly stored entries.


## Photo identity & catalog accuracy correction (October 2026)

Named strain profiles no longer receive unrelated Wikimedia Commons or Pexels
flower pictures as fallback imagery. The shared `/strainprofile` and Find Strains
card only embeds an owner-supplied credited cultivar image, and labels it
owner-submitted rather than independently proven. Source profile links remain
for photo browsing, but a generic shot is not evidence of strain identity.

Archived catalog labels and breeder entries are now explicitly source-specific:
one legacy type or a single commercial seed-bank listing does not establish
the classification and origin of all named variants. For Northern Lights,
independent [Leafly](https://www.leafly.com/strains/northern-lights) and
[Sensi Seeds](https://sensiseeds.com/en/regular/northern-lights-3) listings
support indica / indica-dominant, while the old Kushy row says Hybrid.
Disagreement is shown, not silently flattened into one label.

When enrichment providers do not respond with a verified exact match, the bot
shows one useful status instead of four competing error strings. No status is
misrepresented as a strain detail. Generic photographs may still be used
outside named strain profiles with proper credits.


### Named photo provenance: Northern Lights

A source-identified Northern Lights flower photograph is now available from Wikimedia Commons, uploaded as Northern-lights-flowering.jpg in 2007 by User Dan. License CC BY-SA 3.0, original source https://commons.wikimedia.org/wiki/File:Northern-lights-flowering.jpg. This is source-reported identification, not a genetic certificate. Only exact cultivar-name searches receive it. No generic stock/flower photo is added to other strain results.
