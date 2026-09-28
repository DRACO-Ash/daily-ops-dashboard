**BLUESTAQ LIMITED** | Mattermost Asks | **COMMERCIAL IN CONFIDENCE**

# Mattermost Asks

**Document classification:** Commercial in Confidence
**Data classification:** Unclassified (per ADR-006)
**Owner:** Daily Operations Dashboard Team, Bluestaq Limited
**Last updated:** 2026-09-28
**Audience:** Operators and admins who define what the dashboard pulls from Mattermost.

> **BLUF**
>
> The dashboard pulls nothing from Mattermost unless you ask. An **ask** is a saved, named search you can run now, at a chosen time, or on a refresh interval. A **full-history pull** copies every post from chosen channels at a time you pick. Both live under **Comms**. Analysts can read results; only operators and admins can create, run or schedule.

**SECTION 01**

## Building an ask

Open **Comms**, then **Asks**, then **New ask**. Either describe what you want and press **Suggest** (the assistant drafts the fields for you to check), or fill the fields yourself. Nothing is saved until you press **Save ask**.

| Field | Meaning |
|-------|---------|
| Terms | Every one must appear in the post. Case does not matter; a phrase such as `COSMOS 2589` is matched as written. |
| Any terms | At least one must appear. Use this for synonyms. |
| Authors | Mattermost usernames. Use **Find person** to turn a name into a username. A misspelt username fails the run with an error rather than returning nothing. |
| Channels | Channel URL names. Leave empty for every channel dok.bot is in. |
| After / Before | Inclusive dates, UTC. |
| Include archived (closed) channels | On by default. |
| Scope | **Every matching post**; **Thread starts** (the first post of each thread that matches); **First match in each thread** (the earliest matching post per thread). |
| Extract a value | A regular expression; the first bracketed group is shown in the Extracted column. Run over the post or over the thread title. |
| Refresh | Minutes between automatic re-runs (15 to 10080). Empty means run only when asked. |

Every result carries its thread: thread ID, title (the first line of the first post) and start time, plus a link back to Mattermost. **Download CSV** exports the table.

**SECTION 02**

## Recipes

Replace the example usernames and channel names with the real ones.

● **When each thread was started.** Channels: `jco_dok`. Scope: Thread starts. The Posted and Thread started columns give the time.

● **Thread ID from the title.** As above, plus Extract a value: pattern `(NOTSO-\d{4}-\d{3})`, source thread title. Adjust the pattern to the ID format in your titles.

● **When the fusion provider released a Possible solve.** Terms: `Possible solve`. Authors: the fusion provider's username. Scope: First match in each thread.

● **When the fusion provider released a Verified solve.** As above with Terms: `Verified solve`.

● **All posts by Michael Sellick across all channels.** Authors: his username (use Find person). Channels: empty. Include archived: on. Scope: Every matching post.

● **Photometric changes on COSMOS 2589, open and closed channels.** Terms: `COSMOS 2589`. Any terms: `photometric`, `photometry`, `brightness`, `magnitude`, `light curve`, `flare`, `glint`. Include archived: on. Scope: Every matching post.

**SECTION 03**

## Full-history pulls

**Comms**, then **Full history**. Tick channels (none ticked means every channel dok.bot belongs to), choose **Start now** or a time, and press **Pull full history**. Large channels complete over several minutes; the list shows progress, and a channel the bot cannot read is recorded and skipped. Pulled posts appear under **Messages** and feed the assistant.

**SECTION 04**

## Good practice

● Keep asks narrow. A run that reads more than 20 pages stops and shows **partial**; add a term, author, channel or date range.
● Asks match words literally. If a result is missing, check the wording used in Mattermost and add it to Any terms.
● Every create, change, run, schedule and pull is written to the audit log with your name.

Bluestaq Limited | Daily Operations Dashboard documentation | 2026 | **COMMERCIAL IN CONFIDENCE**
