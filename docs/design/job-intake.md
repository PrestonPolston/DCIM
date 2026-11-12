# Job intake: new job from a DCREQ + ePIF + cable matrix (plan, 2026-11-11)

Status: **design plan, PLAN ONLY (no code).** Desktop only; phone on hold. All DCREQs, file names and counts in examples are **sample data**.

**DB model (read-only):** [docs/db/JOB_INTAKE.md](../db/JOB_INTAKE.md) — planned, not approved, 2026-11-11. This UX uses that document's names and terms (D104–D106 and the tables in §2–§7), plus the Architect's answers to the Designer's §10 (folded in below; they are going into JOB_INTAKE.md). It does not invent a second schema. Each former §10 item is marked **resolved** in **§10**.

DCREQ format and project rules stay in [landing.md](landing.md) (those docs are on hold — referenced, not rewritten). ePIF review details stay in [placement-popup.md](placement-popup.md) §7a–§7g. Home tiles: [home.md](home.md). Cable field list: docs/db/DEVICE_DATA_MODEL.md §3.4, §7 and §8. Field notes: docs/db/PRESTON_FIELD_NOTES.md page 2.

**Goal:** a tech starts a job in three easy steps. Anything missing becomes an **open item** on the job. It can be filled now or held for later (`deferred`) in the fill-later queue. **Missing data never blocks the rest of the batch** (D106).

```
1. Type the DCREQ          →  the job number IS the DCREQ; a new one creates the job
2. Upload the ePIF CSV     →  Space & Power, PSU1 and PSU2 columns
3. Upload the cable matrix →  A/Z ends, hops, cable type/mode
4. Preview → Commit        →  job page with the open-items queue
```

Each **file** is optional. Skipping one still finishes intake and creates an open item (`epif_not_uploaded` or `cable_matrix_not_uploaded`). The **DCREQ is required** to start: there are no untitled jobs, and `missing_dcreq` is dropped. The job is created from the typed number before any upload (JOB_INTAKE.md §2). A missing DCREQ *column in a CSV* is irrelevant; the batch already belongs to the job.

Putting both files in **one wizard** (and wrapping the existing ePIF review) is a **recommendation, pending Preston** — see §9. The screens below are drawn that way so they can be reviewed, not because it is settled.

---

## 1. Decisions in this plan (2026-11-11)

| Topic | Source | Statement |
|---|---|---|
| Job | home.md + JOB_INTAKE.md §2 | A job is a **`projects` row**, labelled by its **primary DCREQ** (`projects.primary_dcreq_id` → `project_references(kind='DCREQ')`). There is no second `jobs` table. Display name defaults to the DCREQ string and is editable later. |
| New DCREQ | this plan, D104 | A **new** DCREQ **creates a new job** when Step 1 is submitted (`POST /jobs`). Attaching more work to an existing job comes **later**. |
| Existing DCREQ | JOB_INTAKE.md §2 | **409 `job_exists`**, naming the existing project id, name and status. Nothing is appended silently. |
| Job number | Preston + D73 | The job number **is** the DCREQ (`DCREQ000` + 4 digits, 12 characters, `^DCREQ000[0-9]{4}$`). The service trims and uppercases. A bad value is **422 `dcreq_format`**; nothing is created. |
| No untitled job | Architect §10, resolved | A valid DCREQ is required at `POST /jobs`. `missing_dcreq` is **dropped**. |
| Queue | Preston + Architect §10 | Tech or admin may fill, defer, un-defer, or dismiss; any signed-in user may read. There is **no assignee**. “Assigned to me” stays **parked**. |
| Item status | Architect §10, resolved | `open` / `deferred` / `resolved` / `dismissed`. **Open** and **deferred** both count as **unresolved**. Deferred means held in the fill-later queue and records who and when; `note` stays. |
| Missing data | Preston, D77/D106 | **Warn only** for row and field data; the batch still commits. The *job itself* always has a DCREQ (typed before upload). |
| Extra PSUs | Preston + placement-popup §7d + JOB_INTAKE.md §6 | The CSV has PSU1/PSU2 only; more than two **prompts** the user when `psu_count` > 2 (or the tech adds one). They become live **`device_psu_assignments`**. |
| Current / overdue / recently closed | Architect §10, resolved | `projects.status` is `open` or `closed`, with `closed_at` and `closed_by`. **Close** and **Reopen** are audited actions with real buttons on the job page. **Current** and **open over 30 days** are computed. Closed jobs stay on Home for **30 days after `closed_at`**. Who may close, and whether leftover unresolved items only warn, is still **question 4**. |
| Abandon / cancel intake | Architect §10, resolved | Hard delete is allowed only for an **empty** job (no committed imports, devices, cables, or resolved items); staged rows go with it. The **creator or an admin** can do it, and it is audited. Otherwise the job is **closed** instead. Wizard uses a plain **Cancel intake** confirm, not a password re-entry. |
| “Assigned to me” | home.md + Architect §10 | **Parked** — no user↔project link. |
| Cable matrix in this intake | this plan + JOB_INTAKE.md §7, supersedes C2 | **Recommendation, pending Preston** (not settled): both files share one wizard, and a cable row whose A or Z end does not resolve is held as an open item (no connection written). Drawn that way in §3–§4. A connection, when committed, is written once **both A and Z ports resolve**; hops, trail, media and IP are fill-later open items. |
| Item expiry | Architect §10 + §9 | **Recommendation, pending Preston** (not settled): open items never auto-expire. The model has no expiry; they stay until resolved or dismissed. |
| Secrets | Architect §10, resolved | Secret or iLO headers make the whole file fail with **422 `import_forbidden_columns`**. The banner lists the **header names only**, never the values, and **nothing is staged**. |

**Tension with earlier ePIF rules (now closed for this path):** placement-popup.md §7a and DB note D76 said *an import never creates a DCREQ or a project*. JOB_INTAKE.md D104/D105 **supersede D76 for this intake path only**: typing a DCREQ the app has never seen creates the job and the reference. A CSV still never creates the job — the typed DCREQ step does. The app still does not invent ticket numbers.

---

## 2. What exists today (read-only, 2026-11-11)

| Piece | Today in apps/api | Gap |
|---|---|---|
| Projects | `GET/POST /projects`, `…/references` (kind can be DCREQ) | No job-intake wizard. No DCREQ format CHECK, no `uq_project_references_dcreq`, no `primary_dcreq_id`, no `projects.status` / `opened_at` / `closed_at` in the live API (all planned in JOB_INTAKE.md, not built) |
| ePIF import | **Not built.** No `job_imports` / `epif_imports`, no `epif_requests` (`epif_ids` is a stub). No `device_psu_assignments` | The whole Space & Power CSV path is design-only (placement-popup.md §7a) |
| Device CSV | `POST /devices/import` (all-or-nothing, `host_name` required) | Different file and rules; **not** the ePIF flow |
| Cables / connections | `GET/POST /connections`, ports on a device, `GET /connections/export` | **No cable-matrix CSV import.** `connection_hops`, `cables.trail` / `external_id` / `project_id`, cable/connection `status`, and `port_ip_config` are planned, not built |
| Home tiles | Planned in home.md; `/` still has no jobs summary in the API | Current jobs / held ePIF tiles are parked. `/home/summary` is specified in §5 (shape is Backend's call) |
| Open-items queue | Nothing | New (`job_open_items`) |

---

## 3. Intake flow (screen by screen)

Entry: Home **[+ New job]** or nav **Import → New job**. Techs and admins. Read-only users don’t see the button.

A short stepper stays on the left: DCREQ → Files → Preview → Done. After Step 1 succeeds, the job exists on the server (`POST /jobs`). Uploads and the preview attach to that job. [Back] never loses uploads.

The one-wizard layout below (ePIF and cable matrix in the same flow, wrapping the existing ePIF review) is a **recommendation, pending Preston**. It is drawn so it can be reviewed; it is not settled. See §9.

### 3.1 Step 1 — Type the DCREQ

```
┌ New job                                                      ✕ ┐
│  1 DCREQ  →  2 Files  →  3 Preview                           │
│                                                              │
│  Job number = DCREQ                                          │
│  [ DCREQ000________ ]   hint: DCREQ000 + 4 digits            │
│  e.g. DCREQ0001234 · paste the full ID, 0001234, or 1234     │
│                                                              │
│  [Cancel]                                      [Next: Files] │
└──────────────────────────────────────────────────────────────┘
```

- Mask/hint `DCREQ000` + 4 digits. Paste of the full ID, the 7 digits, or the last 4 is rebuilt to the canonical form (landing.md search rules, case-insensitive, spaces ignored). The service trims and uppercases before validation.
- **Invalid format:** inline “Enter a DCREQ like DCREQ0001234 (DCREQ000 + 4 digits).” Next stays disabled. If the user somehow submits it, the API returns **422 `dcreq_format`** and nothing is created.
- **Blank:** Next stays disabled. There is no “continue without a DCREQ” path and **no untitled job**. `missing_dcreq` is dropped. (Preston’s “missing DCREQ only warns” applies to row/field data and to a missing DCREQ *column in a CSV*, not to starting the job.)
- **Already exists (409 `job_exists`):** hard stop for v1, because attach-to-existing is later. The banner names the existing job’s name and status: “**DCREQ0001234 is already a job (Leaf refresh, open).** Attaching more work to that job isn’t available yet.” [Open that job] [Use a different DCREQ]. Next stays disabled until the field changes. Whether 409 is right, or the user should be taken to that job immediately, is **question 1**.
- **New and valid:** **Next** calls `POST /jobs`. That creates the `projects` row (`status='open'`, `opened_at` = now, `name` = the DCREQ) and the primary `project_references` row, in one change_set, audit `job.create`. The 30-day *open* clock starts here (pending **question 5**). URLs use `/jobs/{dcreq}` or `/jobs/{project_id}`.
- **Cancel** on this step, before Next succeeds, just closes the wizard. Nothing was created.

### 3.2 Step 2 — Upload the two files (each optional)

```
┌ New job · DCREQ0001234                                       ✕ ┐
│  ✓ 1 DCREQ  →  2 Files  →  3 Preview                         │
│                                                              │
│  Space & Power (ePIF)          Cable matrix                  │
│  ┌ drag or browse .csv  ┐    ┌ drag or browse .csv  ┐      │
│  │ epif_leaf.csv        │    │  no file yet          │      │
│  │ 24 rows · ready      │    │  Skipping adds        │      │
│  └──────────────────────┘    │  cable_matrix_not_    │      │
│                              │  uploaded             │      │
│                                                              │
│  [Cancel intake]  [Back]  [Skip remaining]   [Next: Preview] │
└──────────────────────────────────────────────────────────────┘
```

- `.csv` only, 8 MB max, same as today’s device import (placement-popup.md §7a). [Use a different file] replaces a pick.
- **Skip** a file: Preview still opens. The job gets an unresolved item, type `epif_not_uploaded` or `cable_matrix_not_uploaded` (`source='manual'`, no target row).
- **Unreadable or unknown headers:** the file is rejected; the other file is kept. The user replaces the bad file or skips it. Nothing is staged for the rejected file.
- **Secret or iLO headers** (or any column DEVICE_DATA_MODEL §6 forbids): the whole file fails with **422 `import_forbidden_columns`**. The banner lists the **header names only**, never the values, for example: “This file has forbidden columns: iLO Password. Remove those columns and upload again. Secrets are never stored.” **Nothing is staged.** This is a blocking file error, not an open item.
- A missing DCREQ column inside the CSV is **not** an error: `job_imports.dcreq` is copied from the job, which already exists.
- Staging happens when the file is accepted: `job_imports` (`kind='epif'` or `'cable_matrix'`, status `review`) + `import_rows` (raw cells, `row_number` 1-based). No devices or connections yet.
- **Cancel intake** (also the window ✕): see §3.5. Plain confirm, no password re-entry.

### 3.3 Step 3 — Preview (both files together)

```
┌ Preview · DCREQ0001234                                       ✕ ┐
│  ePIF  24 rows: 20 ready, 3 warning, 1 held                  │
│  Cable 18 rows: 16 ready, 2 warning (hops fill-later)        │
│                                                              │
│  ⚠ Unresolved items that will stay in the queue (4)          │
│  • leaf-sw-04 — no RU                 [Fill now] [Hold later]│
│  • leaf-sw-12 PSU2 — ⚡ Needs power    [Fill now] [Hold later]│
│  • CAB-009 Trail — no trail           [Fill now] [Hold later]│
│  • Upload the cable matrix            [Browse]               │
│                                                              │
│  [Cancel intake]  [Back]    [Commit job — 4 stay in queue]   │
└──────────────────────────────────────────────────────────────┘
```

- One preview for both batches (**recommendation, pending Preston**, same as the one-wizard note in §9). Counts come from `import_rows.result`: `ready`, `warning`, `held`, `conflict`.
- **Ready** and **warning** rows will write their records on commit. Each warning also creates a `job_open_items` row.
- **Held** rows (for example an Install device with no rack, or — **recommendation, pending Preston** — a cable row whose A or Z end does not resolve) write **no** live device or connection. They stay as `import_rows` plus an unresolved item. The batch still commits.
- **Conflict** rows (hostname already in that rack, serial clash, RU overlap, live (port, lane) taken, duplicate live cable label) are **not written**. The rest of the batch still commits, and the row becomes an open item (type `other` until a `conflict_*` type exists, plus `target_field`). Whether that “skip the row and continue” rule is right, or the whole batch should stop, is **question 3**.
- **Fill now** opens the same editors as placement-popup.md §7 (position, profile, PSU Take over / Swap / ⚡ Needs power input, extra PSU prompt). A cable Fill now is a small form for the missing field (device, port, hop, trail, label, media, IP). Saving writes the target field through the normal service and the item will be created already `resolved` (or never opened) on commit.
- **Hold for later** sets the item’s status to **`deferred`**. That records who held it and when; `note` may be added and is kept. The row still follows the ready/warning/held/conflict write rule above.
- Leftover warnings the tech neither fills nor explicitly holds are created as **`open`** (still unresolved, no deferral stamp).
- **Commit stays enabled** with leftover unresolved items (D106). A successful commit is **200** with `warnings[]` and an unresolved-item count. It is never a 4xx because of missing data. Only a bad DCREQ (already handled), a rejected file (including 422 `import_forbidden_columns`), or a confirmed existing job is blocking.

### 3.4 After commit — the job page

```
┌ DCREQ0001234 · Leaf refresh                          open    ┐
│  24 devices · 18 connections · 4 unresolved (1 deferred)     │
│  [Close job]                                                 │
│                                                              │
│  Queue  [Unresolved ▾]   Open  Deferred  Resolved  Dismissed │
│                                                              │
│  ePIF · epif_leaf.csv · leaf-sw-04                           │
│    missing_position · position_u            [Fill] [Hold]    │
│  ePIF · epif_leaf.csv · leaf-sw-12                           │
│    missing_psu · psu_2  ⚡                   [Fill] [Hold]    │
│  Cable matrix · CAB-009 · trail                              │
│    missing_trail  [Deferred]      [Fill] [Un-defer] [Dismiss]│
│  Intake                                                      │
│    cable_matrix_not_uploaded                [Browse] [Dismiss]│
│                                                              │
│  [Upload another file]                                       │
└──────────────────────────────────────────────────────────────┘
```

- Primary label is the DCREQ; the job name (defaulting to that string) can be edited later.
- **Close job** and **Reopen** are real, audited buttons (`job.close` / `job.reopen`) on this page. Reopen sets status back to `open` and clears `closed_at`; the open-over-30-days clock still uses the original `opened_at`. Closing with leftover unresolved items is allowed and only warns (`job_has_open_items`) — **question 4** (recommended: tech/admin, yes, with a warning). Closed jobs leave Current jobs immediately and stay on Home for 30 days after `closed_at`.
- The default queue is **unresolved** items: `status` is `open` or `deferred`. A filter switches the list: Unresolved (default) · Open · Deferred · Resolved · Dismissed · All. Deferred rows show a **Deferred** badge, plus who deferred them and when.
- Grouping is by source file, then device or cable, then field. The list API returns **filename**, **hostname**, and **cable label or trail**, joined at read time (no stored group key).
- **Fill** writes through the normal service in the same change_set, then marks the item **`resolved`** (`resolved_at` / `resolved_by`). Audit `job_open_item.resolve`.
- **Hold for later** (from an `open` item) sets **`deferred`**, records who and when, and keeps `note`. Audit `job_open_item.defer`.
- **Un-defer** returns the **same row** to `open` (it is still unresolved; this is not a new history row). Audit `job_open_item.undefer`.
- **Dismiss** (won’t be filled) requires a short **note**, then marks **`dismissed`** with the resolved columns. Audit `job_open_item.dismiss`.
- Re-opening a **resolved** or **dismissed** fact is a **new row** (the model keeps history; it does not flip that row back to `open`).
- **Upload another file** starts Step 2 on this job. Re-upload of the same file (matching `sha256` for that job and kind) is idempotent: if the batch is not committed it reopens in `review`; if it is already committed, only previously empty fields are filled and open items are refreshed — later manual edits are never overwritten (`assignment_differs_from_import`). A new sha256 is a new batch on the same job.

### 3.5 Cancel intake (wizard only)

[Cancel intake] and the window ✕, after Step 1 has created the job, open a **plain confirm dialog**. No password re-entry (same rule as admin-setup.md).

- If the job is **empty** — no committed imports, no devices, no cables, and no **resolved** items — hard delete is allowed. Staged `job_imports` / `import_rows` go with it. Only the **creator or an admin** can do this. It is audited (`job.abandon`). Copy: “DCREQ0001234 has no committed work. Cancel intake and delete this job, including any staged files?” [Keep working] [Cancel intake and delete].
- Otherwise the job **cannot** be deleted. The dialog offers to **close** it instead: “This job already has committed work, so it can’t be deleted. Close it instead?” [Keep working] [Close job]. Close follows the same rules and audit as the job-page button (question 4).
- Unresolved items (`open` or `deferred`) do not, by themselves, block the empty-job delete: if nothing has been committed or resolved, the job is still empty.

---

## 4. Open items

An open item is **a missing or unfinished fact for this job, pointed at a concrete row and field when one exists** (`job_open_items`).

| Column / field | Role in the UI |
|---|---|
| `item_type` | The kind of fact (list below) |
| `status` | `open` · `deferred` (held in the fill-later queue; records who and when) · `resolved` (the field is now set) · `dismissed` (won’t be filled; `note` required). **Open and deferred both count as unresolved.** |
| Target (at most one typed FK) | `epif_request_id` · `device_id` · `device_psu_assignment_id` · `connection_id` · `cable_id`. Zero of those is allowed when the CSV line never became a record (`import_row_id` still points at the staging row), or for skipped-file types |
| `target_field` | e.g. `position_u`, `profile_id`, `serial_number`, `psu_2`, `port_a`, `hop_3`, `cable_label` |
| `note` | Stays on the row. Dismiss reason, deferral note, or extra context (for example `outlet_taken`) |
| `source` | `epif` · `cable_matrix` · `manual` |
| `import_row_id` | Staging row |
| List labels (joined at read time) | **filename**, **hostname**, and **cable label or trail** — used for grouping and display; not stored as a group key |
| Who / when deferred | Recorded when status is `deferred` (column names follow the DB plan when it lands) |
| `resolved_at` / `resolved_by` | Set when status is `resolved` or `dismissed`; null while unresolved |
| `created_at` / `created_by` | Queue ordering |

**Dedupe:** one unresolved item per job + type + target row + field (unique across `open` and `deferred`). A re-upload refreshes the note and `import_row_id` on the existing unresolved row and does not create a second one.

There is **no item expiry**. That is a **recommendation, pending Preston** (see §9): items stay until resolved or dismissed.

### 4.1 Types

From JOB_INTAKE.md §3, plus the Architect’s §10 additions:

`missing_hostname`, `missing_profile`, `profile_not_usable`, `unresolved_cabinet`, `missing_position`, `missing_serial`, `missing_psu`, `psu_unparsed`, `pdu_missing`, `missing_port`, `unresolved_hop`, `missing_cable_label`, `missing_trail`, `epif_not_uploaded`, `cable_matrix_not_uploaded`, `space_power_flag`, `media_missing`, `ip_missing`, `other`.

`other` plus `target_field` stays the fallback.

How earlier UX labels map:

| UX / earlier name | `item_type` (and `target_field` when it matters) |
|---|---|
| Needs a position / no RU | `missing_position` (`position_u`) |
| Needs a profile | `missing_profile` or `profile_not_usable` (`profile_id`) |
| ⚡ Needs power input | `missing_psu` (`psu_N`) |
| Unparsed PSU cell | `psu_unparsed` |
| Needs power assignment, missing PDU, or outlet taken | `pdu_missing` (note `outlet_taken` when that’s why) |
| Cable A/Z device can’t be resolved | `missing_hostname` (held: no connection written) — **recommendation, pending Preston** |
| Cable A/Z port blank | `missing_port` (`port_a` / `port_z`; held) — **recommendation, pending Preston** |
| Hop1–7 missing or unresolved | `unresolved_hop` (`hop_N`; connection **is** still written) |
| A/Z Row/Rack ambiguous across halls | `unresolved_cabinet` |
| No trail | `missing_trail` |
| No cable label | `missing_cable_label` |
| Cable type, mode, color, length, XCVR, connector, speed | `media_missing` (`target_field` names the field) |
| Network, VLAN, Native VLAN, IP, GW, Mask | `ip_missing` (`target_field` names the field) |
| Hostname / serial / RU / port-lane / label clash; other leftovers | `other` plus `target_field` (pending question 3 for conflicts) |
| Upload the ePIF | `epif_not_uploaded` |
| Upload the cable matrix | `cable_matrix_not_uploaded` |
| S&P flag | `space_power_flag` |

### 4.2 What the preview treats as a row error vs an open item

Driven by JOB_INTAKE.md’s required-versus-fill-later rules. “Row error” here means the *file* is rejected or the *row* cannot be written (`held` / `conflict`). It never fails the rest of the batch unless question 3 says otherwise.

**ePIF (Space & Power)**

| Field / situation | On commit | Open item |
|---|---|---|
| Secret or iLO headers | **422 `import_forbidden_columns`**: file rejected, nothing staged; banner lists header names only | — |
| Unknown or unreadable headers | File rejected, nothing staged | — |
| Install device with no rack (cannot legally exist) | Row **`held`**: no device written | yes, on the import row |
| Hostname already in that rack, serial clash, RU overlap | Row **`conflict`**: not written | `other` plus `target_field` (question 3) |
| Missing profile, unusable profile, unresolved cabinet, missing RU, missing serial | Device **can** still write when placement rules allow; otherwise `held` | `missing_profile` / `profile_not_usable` / `unresolved_cabinet` / `missing_position` / `missing_serial` |
| PSU1 / PSU2 (`A12`-style feed+port, also tolerant of `A 7`) | Copied into **`device_psu_assignments`** when the device is created. A taken outlet is **not** written; the device still commits | `pdu_missing` (note `outlet_taken`) or `psu_unparsed` / `missing_psu` |
| No live side PDU for that feed | Assignment stored with `resolved_pdu_device_id` NULL | `pdu_missing` |
| `psu_count` > 2 and PSU 3+ not entered | Device commits; extra PSUs are added in review (`epif_psus.source='import_review'` or `'manual'`) | `missing_psu` (`psu_N`) |
| `psu_count_mismatch` | Warning only | (warning; not a blocking type) |
| S&P flag on the row | Device can still write | `space_power_flag` |

Until `device_psu_assignments` lands, intake can still stage PSU columns and open items, and defer writing the assignments.

**Cable matrix** — **recommendation, pending Preston** (not settled): a connection is committed only when **both endpoint ports** resolve to devices; a row whose A or Z end cannot be resolved is held as an open item (no connection written). Everything else is fill-later. Drawn that way below so it can be reviewed.

| CSV / UI field | Lands in | Commit without it? |
|---|---|---|
| Action (add / remove / move) | `connections.action` (and status) | **Fill-later** (default `add` if blank; warning) |
| A and Z: Name (hostname) | `device_ports.device_id` | **Held** if both sides can’t be resolved: no connection written; `missing_hostname` on the import row. **Recommendation, pending Preston.** |
| A and Z: Row, Rack (and RU if present) | resolve the device | **Fill-later** if the name already uniquely resolves; **held** if the name is ambiguous across halls (`unresolved_cabinet`) |
| A and Z: Slot, Port | `device_ports.slot`, `.name` | **Held** if port is blank: `missing_port`, `target_field='port_a'` or `'port_z'`. **Recommendation, pending Preston.** |
| A and Z: lane (optional) | `connections.port1_lane` / `port2_lane` (0 = whole port) | **Fill-later**; default 0 |
| Hop1–Hop7 (`panel:port`) | `connection_hops` | **Fill-later**. The A↔Z connection **is** still written; `unresolved_hop` (`hop_N`). A hop that would break one-device-per-(port, lane) is **not** written (conflict, question 3) |
| Trail | `cables.trail` | **Fill-later**, `missing_trail` |
| Cable label | `cables` label | **Fill-later**, `missing_cable_label`. Duplicate live `label` → conflict on that row only |
| Cable type, mode, color, length, XCVR, connector, speed; ID | `cables.*` / `external_id` / `device_ports.transceiver_*`, `.connector`, `.speed_mbps` | **Fill-later**, `media_missing` (ID and TAP fall back to `other` plus `target_field`) |
| Network, VLAN, Native VLAN, IP, GW, Mask | `port_ip_config` | **Fill-later**, `ip_missing` |
| TAP | `device_ports.kind='tap'` | **Fill-later**, `other` plus `target_field` |

Breakout is several rows that share a switch port on different lanes, with hops through an MPO panel — not a special widget.

### 4.3 Who works the queue

Tech or admin may fill, defer, un-defer, or dismiss (same spirit as “any tech/admin can finish held import rows”). Any signed-in user may read. There is **no assignee** column, so “who is tracking this job” is not stored — the cross-job queue is simply unresolved items on current jobs. “Assigned to me” stays parked.

---

## 5. How this ties to the home page

[home.md](home.md) tiles read as follows once this plan is built. home.md still needs a later pass: it currently derives “closed” from device status, while this plan uses stored `projects.status`.

`GET /home/summary` returns **current jobs**, **jobs open over 30 days**, **unresolved items by type**, and **jobs closed in the last 30 days**. The response shape is **Backend’s call**.

| Home tile | After this plan |
|---|---|
| **Current jobs** | Computed: `projects.status = 'open'` and not deleted. Sorted by `opened_at`. |
| **Open over 30 days** | Computed: current AND `opened_at < now() - 30 days`. Never a stored flag (it would go stale at midnight). Clock start and reopen behaviour: **question 5**. |
| **Unresolved items by type** | `job_open_items` with status `open` or `deferred`, grouped by `item_type`. Held *import rows* (`import_rows.result = 'held'`) stay a separate count from fill-later *items*. |
| **Closed in the last 30 days** | `status = 'closed'` AND `closed_at` within 30 days. These jobs leave Current jobs immediately and stay on Home (workload / recently closed) until that window ends. Close / Reopen are the job-page buttons in §3.4. Closing with leftover unresolved items only warns — **question 4**. |
| Empty / error | Unchanged from home.md. |

Home search still finds DCREQs by full ID, 7 digits, or last 4.

---

## 6. Worked example (sample data)

Tech types **DCREQ0001234**. The app has never seen it, so `POST /jobs` creates the job (Leaf refresh as the later-edited name). They upload `epif_leaf.csv` (24 data rows) and skip the cable matrix.

- 20 ePIF rows `ready`.
- 3 `warning`: leaf-sw-04 has no RU (`missing_position`); leaf-sw-12’s PSU2 cell is empty and `psu_count` expects it (`missing_psu`, `target_field='psu_2'`); one row’s `A12` value will not parse (`psu_unparsed`).
- 1 `held`: an Install row with no rack — no device written; unresolved item on that `import_row_id`.

They Fill now the PSU2 on leaf-sw-12 in the preview (typed `B14`), Hold for later on the unparsed PSU, and leave the missing RU as `open`. Commit is **200**, unresolved count 4: `missing_position` (open), `psu_unparsed` (`deferred`), the held Install row (open), and `cable_matrix_not_uploaded` (open). leaf-sw-12 is committed with its `device_psu_assignments`. The job is current. On Home, Current jobs shows DCREQ0001234 with “4 unresolved (1 deferred).”

A week later any tech un-defers or fills as needed, and uploads the cable matrix. Sixteen cable rows have both A and Z ports and commit as connections; two have hops or a trail to fill (`unresolved_hop` / `missing_trail`) and still write the A↔Z connection. (Holding a cable whose A or Z end never resolved, instead of failing that row as a file error, is a **recommendation, pending Preston**.)

If the tech had cancelled the wizard before any commit, Cancel intake would hard-delete the empty job and the staged ePIF. After this commit, Cancel intake is no longer offered; they would use **Close job**.

---

## 7. Impact on the ePIF import that is already designed

placement-popup.md §7a–§7g stays the reference for row status, Fill / Hold, S&P, PSU parsing, Take over / Swap, and ⚡ Needs power input. The intake **wrapper** below does not replace that table.

The following wrapper changes — including putting the cable matrix in the **same wizard** — are a **recommendation, pending Preston** (not settled). They are listed so they can be reviewed. See §9.

Concrete shifts, all still plan-only, and all pending that go:

1. **D76 superseded for this path (D104/D105).** The *typed* DCREQ creates the job. The CSV never does. Manual DCREQ input *inside* a file still belongs to a later “attach to existing” path; on this path the batch already has the job’s DCREQ.
2. **Open items, not only per-row Hold.** A warning or held row in the ePIF table also becomes a `job_open_items` row so it shows on the job and on Home after commit. Hold for later sets `deferred`.
3. **Same wizard as the cable matrix.** ePIF-only import can stay as a shortcut that starts this wizard with the DCREQ already known and the cable slot empty (`cable_matrix_not_uploaded` if they skip it).
4. **Commit is 200 with warnings.** Ready and warning rows write; held and conflict rows don’t; missing fields never 4xx the batch.
5. **Secret or iLO headers fail the file** with **422 `import_forbidden_columns`**. The banner lists header names only, never values, and nothing is staged.

The review table, counts (`N ready · N held · N errors`), and editors are unchanged. Word “held” in that table means `import_rows.result`, not item status `deferred`.

---

## 8. Backend / DB asks (aligned with JOB_INTAKE.md and the Architect’s §10 answers; planned, not approved)

Use the Architect’s names. Do not invent parallel tables. All of this stays **held until Preston’s go** (their §9). Where JOB_INTAKE.md still shows the earlier `open` / `filled` / `dismissed` wording, prefer the §10 answers folded here (`open` / `deferred` / `resolved` / `dismissed`, the new `item_type`s, 422 `import_forbidden_columns`, empty-job abandon, `/home/summary`).

**Job key and status**
- Job number is the DCREQ on `project_references(kind='DCREQ', ref)`. Format CHECK, `uq_project_references_dcreq (ref) WHERE kind = 'DCREQ'` (each DCREQ, one project). `projects.primary_dcreq_id` set at creation.
- `projects.intake_id` is **not** the key; new jobs leave it NULL. No untitled jobs; `missing_dcreq` is dropped.
- `POST /jobs` (or intake start): validate → create job + primary reference in one change_set, or **409 `job_exists`**, or **422 `dcreq_format`**. Additional DCREQs on the same project are **out of v1** (question 2).
- Stored `projects.status` `'open'` \| `'closed'`, plus `opened_at`, `closed_at`, `closed_by`. Current, open-over-30-days, and closed-in-the-last-30-days are **computed**. Close / Reopen are audited actions with real buttons. Read-only users: 403 on write.
- **Abandon:** hard delete only when the job is empty (no committed imports, devices, cables, or resolved items); staged rows go with it. Creator or admin; audited (`job.abandon`). Otherwise close the job instead.

**Imports**
- `job_imports` (one row per uploaded file, `kind` `'epif'` \| `'cable_matrix'`) and `import_rows` (`result` `'ready'` \| `'warning'` \| `'held'` \| `'conflict'` \| `'committed'` \| `'skipped'`).
- Stage → validate → commit as in JOB_INTAKE.md §5. Commit of writable rows is one change_set. Audit `job_import.stage` / `.commit` / `.abandon`.
- Secret or iLO headers: **422 `import_forbidden_columns`**, header names only in the error payload, nothing staged.
- `epif_requests` + `epif_psus` (request-time PSU1/PSU2 and extras). On commit, parsed PSU rows copy into **`device_psu_assignments`**. Taken outlet: do not write the assignment; open item `pdu_missing`.

**Open items**
- `job_open_items` with the typed FKs, `target_field`, `item_type` (including `epif_not_uploaded`, `cable_matrix_not_uploaded`, `space_power_flag`, `media_missing`, `ip_missing`; `other` plus `target_field` as fallback), `status` (`open` / `deferred` / `resolved` / `dismissed`), `source`, `note`, who/when deferred, `resolved_at` / `resolved_by`, `import_row_id`. Dedupe unique among unresolved rows (`open` and `deferred`). Audit `job_open_item.create` / `.defer` / `.undefer` / `.resolve` / `.dismiss`.
- List API returns **filename**, **hostname**, and **cable label or trail**, joined at read time.
- No assignee. No item expiry (recommendation, pending Preston).

**Home**
- `GET /home/summary` returns current jobs, jobs open over 30 days, unresolved items by type, and jobs closed in the last 30 days. **Response shape is Backend’s call.**

**Cables**
- Prerequisite: `connection_hops`, `cables.trail` / `external_id` / `project_id`, status, `port_ip_config` as in DEVICE_DATA_MODEL §7, if they have not already landed.
- Commit a cable row once both A and Z ports resolve; hops / trail / media / IP become open items. Holding an unresolved A or Z end as an open item (no connection written) is a **recommendation, pending Preston**.

**Lookups**
- Exact match on the normalized DCREQ; contains-search (`1234`) via `LIKE` (trigram later). `/jobs/{dcreq}` or `/jobs/{project_id}`.

---

## 9. Open questions for Preston (combined, at most five)

The DB Architect’s five (JOB_INTAKE.md §11) are the list we are asking. The Designer’s earlier five are mapped under each, or marked duplicate / moved to the recommendations list so they are not asked twice.

**Resolved from Preston’s 2026-11-11 intake direction (plan only; not a build GO):**

1. When the typed DCREQ already exists: **409 `job_exists` for v1** (attach to an existing job comes later). [Open that job] stays a way *out* of the wizard, not attach. Matches “a new DCREQ creates a new job; attaching comes later.”
2. ~~(moved below as still open: additional DCREQs on a v1 job)~~

**Still open (need Preston before build):**

2. May a v1 job carry **additional DCREQs** besides the primary, or is that later only?
   - *New from the DB Architect.* Designer had assumed extra DCREQs stay later (landing.md: a project may have several, but this wizard only creates the primary). Today’s direction names the job by its primary DCREQ; it does not settle extra refs on the same job in v1.

3. **Conflicts** the database would reject (hostname already in that rack, serial clash, RU overlap, one device per port): skip that row, warn, and still commit the rest (recommended), or stop the whole batch?
   - *New from the DB Architect.* The preview in §3.3 is drawn with the recommended “skip the row, commit the rest” rule.

4. Who may **close** a job, and may they close it while open items remain (recommended: tech/admin, yes, with a warning)?
   - *New from the DB Architect.* Close and Reopen are now real buttons on the job page; this question is still the decision. home.md had derived “closed” from device status.

5. Does the **30-day clock** start when the DCREQ is typed (recommended) or when the first file is committed? Does reopen reset it (recommended: no)?
   - *New from the DB Architect.* Designer had used “open more than 30 days” on Home without pinning the start. (The separate 30-day window for *closed* jobs uses `closed_at` and is already in the model.)

**Recommendations (updated 2026-11-11 from Preston’s intake direction):**

- **One wizard for the ePIF and the cable matrix** — **Resolved yes.** Matches “enter the job number, input the space and power sheet and the cable matrix.” Includes the ePIF-import wrapper changes in §7 (open items on the job, Hold for later → `deferred`, cable slot in the same flow). *Designer earlier Q2.*
- **Holding cables with an unresolved A or Z end as open items** (no connection written; `missing_hostname` / `missing_port`) — **Resolved yes.** Matches “missing information goes to a fill-later queue.” *Designer earlier Q3.*
- **Open items never auto-expire**; they stay in the queue until resolved or dismissed. Still the working default (DB plan has no expiry); not an explicit Preston call. *Designer earlier Q4.*

**Designer question not re-asked:**

- *Earlier Q1* (“Creating a job from a typed DCREQ changes D76; is that what you want?”) — JOB_INTAKE.md D104/D105 already proposes this, pending your go on the whole plan. Not asked again here.

---

## 10. Architect answers to the Designer’s gaps (resolved, 2026-11-11)

The items below were the Designer’s §10 list. The Architect has answered them. Each is **resolved** and folded into the UX above. (These answers are going into JOB_INTAKE.md; that file may still show earlier wording until it is updated.)

1. **Stored job status vs home.md’s derived status.** **Resolved.** `projects.status` is `open` or `closed`, with `closed_at` and `closed_by`. Close and Reopen are audited actions with real buttons on the job page. “Current” and “open over 30 days” are computed. Closed jobs stay on Home for 30 days after `closed_at`. home.md still needs a later pass to drop derived-from-devices closed status.
2. **“Held” on items vs “held” on import rows.** **Resolved.** Item status is `open` / `deferred` / `resolved` / `dismissed` (`filled` is replaced by `resolved`). **Deferred** means held in the fill-later queue and records who and when; `note` stays. Open and deferred both count as unresolved. “Hold for later” sets `deferred`. The queue has a Deferred filter and badge, and an **Un-defer** action (same row returns to `open`). `held` on `import_rows.result` is unchanged (the row cannot legally be written).
3. **Starting without a DCREQ.** **Resolved.** There are no untitled jobs, and `missing_dcreq` is dropped.
4. **iLO / secret headers.** **Resolved.** Secret or iLO headers make the whole file fail with **422 `import_forbidden_columns`**. The banner lists the header names only, never the values, and nothing is staged.
5. **Skipped-file open items.** **Resolved.** New types: `epif_not_uploaded`, `cable_matrix_not_uploaded`.
6. **S&P flags after commit.** **Resolved.** New type: `space_power_flag`.
7. **Fill-later cable media / IP types.** **Resolved.** New types: `media_missing`, `ip_missing`. `other` plus `target_field` stays the fallback.
8. **Grouping labels.** **Resolved.** The list API returns filename, hostname, and cable label or trail, joined at read time. No stored group key.
9. **Hold / dismiss note vs a dedicated hold reason.** **Resolved.** `note` stays (no separate reason enum).
10. **Who is tracking a job.** **Resolved.** There is no assignee; “assigned to me” stays parked.
11. **Home summary payload, and closed jobs on Home for 30 days.** **Resolved.** `/home/summary` returns current jobs, jobs open over 30 days, unresolved items by type, and jobs closed in the last 30 days. The response shape is Backend’s call. Closed-in-the-last-30-days uses `closed_at` (see item 1).
12. **Item expiry.** **Resolved with the Architect** (the model has no expiry). Still a **recommendation, pending Preston** — see §9. Do not treat “never auto-expire” as a Preston decision.
13. **Audit events.** **Resolved**, with names updated for the new statuses: `job.create` / `.close` / `.reopen` / `.abandon`, `job_import.stage` / `.commit` / `.abandon`, `job_open_item.create` / `.defer` / `.undefer` / `.resolve` / `.dismiss`.
14. **Empty job after Step 1.** **Resolved.** Hard delete is allowed only for an empty job (no committed imports, devices, cables, or resolved items); staged rows go with it. The creator or an admin can do it, and it is audited. Otherwise the job is closed instead. The wizard has a **Cancel intake** confirm — a plain dialog, not a password re-entry.

**Still pending Preston (not §10, see §9):** questions 2–5 (extra DCREQs in v1, conflict commit rule, who may close, 30-day clock). Q1 and the one-wizard / unresolved-A-Z recommendations are resolved from his 2026-11-11 intake direction; item-expiry stays the working default. Build stays plan-only until he says go.

---

## 11. Pointers

- [landing.md](landing.md) — DCREQ format, several DCREQs per project, derived *device/project* status (on hold; not rewritten here)
- [home.md](home.md) — post-login home, Current jobs / held rows / workload; stored job status and `/home/summary` in §5 of this doc will need a later pass there
- [placement-popup.md](placement-popup.md) §7a–§7g — ePIF review table, PSU parse, Take over / Swap, ⚡ Needs power input (secrets: 422 `import_forbidden_columns`, §3.2)
- [docs/db/JOB_INTAKE.md](../db/JOB_INTAKE.md) — DB plan this UX is written against (read-only from design; §10 answers may still be landing there)
- docs/db/DEVICE_DATA_MODEL.md §3.4, §7, §8 — cable / hop / trail / IP fields
- docs/db/PRESTON_FIELD_NOTES.md page 2 — field experience
- [docs/design/README.md](README.md) — index
