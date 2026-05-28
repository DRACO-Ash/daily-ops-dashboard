# Analyst Training Manual

**Classification:** Unclassified
**Owner:** Daily Operations Dashboard Team, Bluestaq Limited
**Version:** 0.1
**Last updated:** 2026-05-27
**Audience:** Watch analysts new to the Daily Operations Dashboard, plus the trainers delivering induction. Sections labelled **Trainer note** are for delivery, not for the trainee handout.

## What this dashboard is for

The Daily Operations Dashboard is your watch-stand surface. It pulls live operational data from the Unified Data Library (UDL) and renders it in a way you can search, filter, and act on without leaving the tab. As more sources come online (Notice to Space Operators, Tactical Reports, Mattermost activity, ClickUp tasks, procedure documents), they will all appear here.

**Why care?** Time-on-task during a watch is the metric. Every minute you save on stitching context together is a minute back on actual analysis.

## Glossary

| Term | Meaning |
|------|---------|
| **SDA** | Space Domain Awareness. The mission area this dashboard serves. |
| **UDL** | Unified Data Library. The US Space Force's authoritative repository for SDA data. We pull from it; we do not write to it. |
| **Element set / elset** | A snapshot of an object's orbit at a given epoch. Includes mean motion, eccentricity, inclination, and related orbital elements. |
| **TLE** | Two-Line Element. The classic textual representation of an element set. UDL exposes both the parsed values and the raw `line1`/`line2`. |
| **Epoch** | The exact time the orbital state in an element set is valid. ISO 8601 UTC, microsecond precision. |
| **NORAD catalogue number / sat number** | The persistent integer identifier for a tracked object. The ISS is `25544`. |
| **TACREP** | Tactical Report. A UDL-distributed operational notification. |
| **NOTSO** | Notice to Space Operators. UDL-distributed advisory communications. |
| **Mean motion** | Revolutions per day. Low Earth orbit is roughly 14 to 16. |
| **Eccentricity** | How elliptical an orbit is. 0 is a circle; close to 1 is highly elliptical. |
| **Inclination** | Degrees between the orbit plane and the equator. 0 is equatorial, 90 is polar. |
| **RAAN** | Right Ascension of Ascending Node. Where the orbit crosses the equator going north. |

**Trainer note:** Walk the trainee through the glossary before logging in. Roughly five minutes. Use the ISS (`25544`) as a worked example since it appears in every UDL training set.

## Signing in

1. Open `https://<your-dashboard-host>` in a modern browser (Chrome, Edge, or Firefox).
2. Enter your username and password.
3. You arrive on the **Dashboard** landing page.

**Current limitation:** Authentication is stubbed during Phase 1. Any non-empty username is accepted. Real password validation lands in the next slice. Until then, sign in with your normal username and any password.

**Trainer note:** Make clear to the trainee that this is temporary. Show them the audit log row that gets created on every action, so they understand that "no auth" does not mean "no accountability".

## The Dashboard landing page

The landing page lists the data surfaces available to you. At launch:

● **Element sets** — UDL orbital state vectors.

More land each sprint.

## The Element sets page

This is the first operational surface and the template for everything that follows.

### Layout

The page has two cards stacked vertically.

● **Trigger UDL ingest** at the top. The control panel for pulling fresh data from UDL.
● **Filter and results** below. The searchable, paginated table of what we have stored.

### Pulling fresh data from UDL

You will not always need to pull. Background scheduled ingest is on the backlog. For now, when you need fresh data, do this:

1. Set **Epoch since** to the lower bound. Anything with an epoch on or after this moment is in scope.
2. Optionally set **Satellite number**. Leave blank to pull across all objects.
3. Optionally set **Max results** to bound the size of a single pull. UDL's natural cap is around a thousand records; if you want less, set the cap here.
4. Click **Pull from UDL**.
5. Read the success banner. It says: `Pulled N · Inserted N · Updated N · Skipped N`. Most of the time, **Inserted** is what you care about.

**What the counts mean:**

● **Pulled** — how many records UDL returned for your query.
● **Inserted** — new records we did not already have. These are now in the table.
● **Updated** — records UDL has refreshed since we last saw them. The new version overwrites the old.
● **Skipped** — records UDL returned without the minimum fields we need (an `id`, a `satNo`, an `epoch`). These are not lost upstream; we just do not store them.

**Trainer note:** Have the trainee pull for ISS (`satNo=25544`) with an "epoch since" of a week ago. The result is usually under 20 rows: small enough to look at, big enough to learn from. This also gives you a stable demo for every cohort.

### Reading the results table

Columns currently shown:

● **Sat No** — NORAD catalogue identifier.
● **Epoch** — when the element set is valid, in UTC.
● **Mean motion** — revolutions per day, six decimal places.
● **Eccentricity** — six decimal places.
● **Inclination** — degrees, four decimal places.
● **Source** — who in UDL produced the record (for example `18 SPCS`).

Records you cannot see in the table are still in the database (raw payload preserved). A detail view that surfaces every field is on the backlog.

### Filtering and pagination

● **Filter by satellite number** narrows the table to a single object. Type a NORAD number and click **Apply**.
● **Clear** removes the filter.
● **Previous** and **Next** at the bottom walk pages of 50 rows. The footer line tells you which page you are on out of the total.

### Sorting

The table is currently fixed to **epoch descending** (most recent first). Sortable columns are on the backlog.

## Common analyst workflows

### Workflow 1: "Has UDL got anything new on object 25544 today?"

1. **Filter by satellite number** → `25544` → **Apply**.
2. Look at the top row's **Epoch**. If it is within today, you are current.
3. If not, run **Pull from UDL** with **Epoch since** set to the start of today and **Satellite number** set to `25544`.
4. Recheck the top row.

### Workflow 2: "Quick sweep across everything UDL sent overnight"

1. Run **Pull from UDL** with **Epoch since** set to 24 hours ago. Leave satellite number blank. Set **Max results** to `1000` to keep the pull bounded.
2. Read the banner. **Inserted** is the new traffic.
3. Filter and read as needed.

**Trainer note:** This is a good moment to remind the trainee that every pull they trigger appears in the audit log. Encourage them to think about pulls as deliberate operational events, not background polling.

## What the dashboard does not do (yet)

● **Detail view.** Clicking a row does not expand it. The raw UDL payload is in the database but not yet on screen.
● **Sortable columns.** Header clicks have no effect.
● **Saved searches.** You cannot bookmark a filter.
● **Scheduled ingest.** Every pull is manual.
● **NOTSO, TACREP, Mattermost surfaces.** These are coming. Same shape as Element sets.

If you find yourself wishing the dashboard did something it does not, tell the team. The backlog is a living thing.

## When something goes wrong

| Symptom | Action |
|---------|--------|
| Page will not load | Refresh. Then check the dashboard status with whoever runs the host. |
| Sign-in fails | The auth stub accepts any non-empty username. If even that fails, the backend is probably down. Report it. |
| **Pull from UDL** shows a red error banner | The message will say what failed. UDL rejected credentials, UDL is unreachable, or UDL returned an unexpected shape. Either way, ask the operator to check `UDL_USERNAME`, `UDL_PASSWORD`, and the UDL status. |
| Table is empty when you expect rows | Confirm your filter is what you think. The empty-state message says "No element sets to show." Clear the filter and check again. |

The operator-facing playbook for these is in [docs/runbook/operator-manual.md](../runbook/operator-manual.md).

## Trainer notes: delivering this material

● **Time budget.** A first-pass session runs comfortably in 45 minutes: 10 for glossary, 10 for sign-in and landing, 20 for the Element sets page, 5 for Q&A.
● **Hands-on first.** Have the trainee run their own ingest as soon as the glossary is covered. The dashboard makes far more sense when they have done it once than when they have only watched.
● **Stable example.** The ISS (`25544`) is reliable. There are always recent element sets for it, and the trainee may recognise the object, which lowers cognitive load.
● **The audit log is the punchline.** Pull up the audit log after the trainee's first ingest and show them their own entry. This sells the operational discipline more effectively than any talk.
● **Common questions and answers.**

  | Question | Answer |
  |---|---|
  | "Why is the sign-in so loose?" | Stubbed during Phase 1. Real authentication is the next slice. Auditing still applies. |
  | "Where are NOTSOs and TACREPs?" | Same pattern, later sprints. |
  | "Can I delete a pull?" | No. Records can be overwritten by a fresher pull, but rows are not removed by the application. The audit log is append-only. |
  | "What if UDL changes the schema?" | We store the raw payload. Nothing is lost. New typed columns may follow in a migration. |

## Feedback

The dashboard exists to make watch easier. If anything on this page is unclear, or if a workflow is missing, tell the team in `#ops-dashboard` (Mattermost) or open an issue. Phase 1 is the moment to shape the surface.
