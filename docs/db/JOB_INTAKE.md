# Job intake (DCREQ + ePIF + cable matrix): plan

**Status: PLANNED, not approved. Needs Preston's go.** DB Architect, 2026-11-11 ~9:45 AM CST; **Rev 2 ~9:50 AM CST: answers the Designer's job-intake.md §10 (D109).** Docs only: no schema or code.
**Inputs (read-only):** DEVICE_DATA_MODEL.md §3.2–§3.4, §5.5–§5.6, §7–§8; DESIGN.md D11, D73–D77 and the `epif_imports` note; BACKEND-WORKITEMS "D75/D76 DCREQ intake"; PDU_SIDE_MOUNT_PLAN.md D59–D77 (especially D62–D68, D71, D77). Models and migrations at main head `978d120` (Alembic head `p1_27_repair_check_names`). The `feat/cabinet-profiles` branch (`p1_28`/`p1_29`) does not change projects, imports or cables and is not needed here.
**Designer UX:** `docs/design/job-intake.md` was not in the tree when this was written. §10 lists the assumptions that doc should use. Answers to the Designer's four questions are in **§2, §3, §6 and §7**.

Flow: the user types a **DCREQ** (the job number), uploads the **ePIF Space & Power CSV**, then the **cable-matrix CSV**. Anything missing becomes an **open item** (fill now, or hold in the fill-later queue). Missing data **only warns and never blocks commit** (D77, confirmed for this plan as D106).

---

## 1. Scope and grounding (code today)
- **Exists:** `projects`, `project_references` (kind CHG/DCREQ/INC/OTHER, `uq(project_id, kind, ref)`, `ix(kind, ref)`). `projects.intake_id` is a free `VARCHAR(64)` with a partial unique, **no DCREQ format CHECK**. No project status. No `epif_requests`/`epif_psus`/`epif_imports`. No `device_psu_assignments`. Import today is create-only device CSV under `change_sets.source='csv_import'`.
- **Cables (item 32, partial):** `device_ports` (including nullable `lanes`/`rear_port_id`) and `cables`/`connections` exist. **Not built:** `connection_hops`, breakout lanes > 0, cable/connection `status`, `cables.trail`/`external_id`/`project_id`, `port_ip_config`. This plan **includes those cable-matrix tables** (DEVICE_DATA_MODEL §7) as a prerequisite revision, or they land immediately before the cable import.
- **Held, unbuilt, already renumbered** (after cabinet-profile p1_28/p1_29): `p1_30_project_dcreq` → `p1_31_device_project_indexes` → `p1_32_epif_import_dcreq`. This plan **expands** them (§9).

---

## 2. How a job is keyed by DCREQ (Designer Q1)
- The **job number is the DCREQ**. Format is unchanged (D73): 12 characters, `^DCREQ000[0-9]{4}$` (e.g. `DCREQ0001234`). The service **trims and uppercases** before validation. A bad value gives **422 `dcreq_format`** and nothing is created.
- A **job is a `projects` row**. There is no second `jobs` table.
- The DCREQ is stored as `project_references(kind='DCREQ', ref=<normalized>)`, with:
  - `ck_project_references_dcreq_format` (null-tolerant of other kinds; SQLite: `kind <> 'DCREQ' OR (length(ref) = 12 AND ref GLOB 'DCREQ000[0-9][0-9][0-9][0-9]')`; PG: `kind <> 'DCREQ' OR ref ~ '^DCREQ000[0-9]{4}$'`).
  - **`uq_project_references_dcreq (ref) WHERE kind = 'DCREQ'`** — each DCREQ belongs to **one** project (D75, kept).
  - **`projects.primary_dcreq_id`** INT NULL, FK `project_references(id)` **ON DELETE RESTRICT**, unique where not null. Set at job creation to that reference. The job's display name defaults to the DCREQ string (editable later; the key stays the reference).
- **`projects.intake_id` is not used as the key** (closes Q-D2 for this flow: matching is by DCREQ). Existing `intake_id` values stay as legacy text until an admin migrates them. New jobs leave `intake_id` NULL.
- **Creating a job** (`POST /jobs` or the intake start):
  1. Normalize and validate the typed DCREQ.
  2. **If no `project_references` row exists:** insert `projects` (status `open`, `opened_at` = now, `intake_date` = today, `name` = the DCREQ) and the DCREQ reference, and set `primary_dcreq_id`, all in **one change_set**. Audit `job.create`. **This is the v1 rule (D104): a new DCREQ creates a new job.**
  3. **If the DCREQ already exists:** **409 `job_exists`**, naming the existing project id, name and status. **Attaching more work to an existing job is later (D104).** Nothing is appended silently. (Q1 asks Preston to confirm this 409.)
- The DCREQ is still a **ticket created elsewhere** (D76's "the app does not invent ticket numbers" is kept). What changes is that **typing a DCREQ the app has never seen creates the job and the reference in the app**. That **supersedes D76's "the import never creates a DCREQ or a project"** for this intake path only. A CSV is never the thing that creates the job: the typed DCREQ step is.
- Additional DCREQs on the same project (D75, many per project) are **out of v1**. The unique still allows them later.
- **Lookups:** exact match on the normalized value via `uq_project_references_dcreq` / `ix_project_references_kind_ref`. A "contains" search (`1234`) uses `LIKE` (PG trigram later, item 18). URLs and APIs use `/jobs/{dcreq}` (normalized) or `/jobs/{project_id}`.

### 2.1 Job status: "current" and the 30-day flag
New columns on `projects`:
- `status VARCHAR(12) NOT NULL DEFAULT 'open'`, `ck_projects_status IN ('open','closed')`.
- `opened_at TIMESTAMP NOT NULL` (set at creation; never rewritten on reopen — Q5).
- `closed_at TIMESTAMP NULL`, `closed_by VARCHAR(128) NULL`.
- `ck_projects_closed`: `(status = 'closed') = (closed_at IS NOT NULL)`.

**Computed, not stored** (never a stored flag, which would go stale at midnight):
- **Current** = `status = 'open' AND deleted_at IS NULL`.
- **Overdue / "open over 30 days"** = current AND `opened_at < now() - 30 days`.
- **Recently closed** (home workload tile) = `status = 'closed' AND deleted_at IS NULL AND closed_at >= now() - 30 days`. This is a **second 30-day rule**, measured from `closed_at`, not from `opened_at`.

**Indexes** (identical SQL on SQLite and PG):
- `ix_projects_current_opened_at ON projects (opened_at) WHERE status = 'open' AND deleted_at IS NULL` — current and overdue queues.
- `ix_projects_recently_closed ON projects (closed_at) WHERE status = 'closed' AND deleted_at IS NULL` — home's "closed within 30 days" list.

`status` is **stored** (`open`/`closed`, named CHECK). **Close and reopen are first-class, audited actions** (`job.close` / `job.reopen`), not a by-product of the last device changing state. Reopen sets status back to `open` and clears `closed_at`/`closed_by` (the overdue clock still uses the original `opened_at`). Closing with unresolved items is allowed and only warns (`job_has_open_items`); Q4.
The API returns `current`, `overdue`, `recently_closed`, `days_open` and `days_since_closed`. See §5.1 for `GET /home/summary`.

---

## 3. Open items / fill-later (Designer Q2)
One table, `job_open_items`. An item is "a missing or unfinished fact for this job, pointed at a concrete row and field when one exists."

```
job_open_items (
  id PK,
  project_id           INT NOT NULL FK projects ON DELETE RESTRICT,
  item_type            VARCHAR(32) NOT NULL,   -- ck_job_open_items_item_type, list below
  status               VARCHAR(16) NOT NULL DEFAULT 'open',
                       -- ck IN ('open','deferred','resolved','dismissed')
  -- exactly one target, or none (the fact has no row yet):
  epif_request_id      INT NULL FK epif_requests ON DELETE SET NULL,
  device_id            INT NULL FK devices ON DELETE SET NULL,
  device_psu_assignment_id INT NULL FK device_psu_assignments ON DELETE SET NULL,
  connection_id        INT NULL FK connections ON DELETE SET NULL,
  cable_id             INT NULL FK cables ON DELETE SET NULL,
  import_row_id        INT NULL FK import_rows ON DELETE SET NULL,  -- staging row (§5)
  target_field         VARCHAR(64) NULL,       -- e.g. 'position_u', 'profile_id', 'serial_number',
                                               -- 'psu_2', 'port_a', 'hop_3', 'cable_label'
  note                 TEXT NULL,
  source               VARCHAR(16) NOT NULL,   -- ck IN ('epif','cable_matrix','manual')
  created_at, created_by,
  deferred_at          TIMESTAMP NULL,
  deferred_by          VARCHAR(128) NULL,
  resolved_at          TIMESTAMP NULL,
  resolved_by          VARCHAR(128) NULL,
  change_set_id        INT NULL FK change_sets SET NULL,
  ck_job_open_items_status: status IN ('open','deferred','resolved','dismissed'),
  ck_job_open_items_deferred: (status = 'deferred') = (deferred_at IS NOT NULL),
  ck_job_open_items_resolved: (status IN ('open','deferred')) = (resolved_at IS NULL),
  -- unresolved = status IN ('open','deferred') (both count for job flags and the fill-later queue)
  ck_job_open_items_one_target:
    (CASE WHEN epif_request_id IS NOT NULL THEN 1 ELSE 0 END
   + CASE WHEN device_id IS NOT NULL THEN 1 ELSE 0 END
   + CASE WHEN device_psu_assignment_id IS NOT NULL THEN 1 ELSE 0 END
   + CASE WHEN connection_id IS NOT NULL THEN 1 ELSE 0 END
   + CASE WHEN cable_id IS NOT NULL THEN 1 ELSE 0 END) <= 1,
  -- dedupe among open items (one open item per job + type + target row + field):
)
```

**Target design: typed nullable FKs, not a polymorphic `(entity_type, entity_id)`.**
- Real FKs (SET NULL when the row is deleted or decom'd), so the queue never points at a ghost id.
- The CHECK guarantees at most one target. Zero targets is allowed for "this CSV line never became a record" (held entirely in `import_row_id`).
- Adding a new target kind is a small migration. A polymorphic column cannot have a portable FK and would need a CHECK on the type string anyway.

**`item_type` (extensible by CHECK-swap).** There is **no `missing_dcreq`**: v1 has no untitled jobs; a valid DCREQ is required at `POST /jobs`.
`epif_not_uploaded`, `cable_matrix_not_uploaded`,
`missing_hostname`, `missing_profile`, `profile_not_usable`, `unresolved_cabinet`, `missing_position`, `missing_serial`,
`missing_psu`, `psu_unparsed`, `pdu_missing`,
`missing_port`, `unresolved_hop`, `missing_cable_label`, `missing_trail`, `media_missing`, `ip_missing`,
`space_power_flag`,
`other`.
Skipped-file items (`epif_not_uploaded` / `cable_matrix_not_uploaded`) have **no target FKs**, `source='manual'`, and are auto-`resolved` when that kind of file is later committed on the job. `space_power_flag` is used for post-commit Space & Power check flags (placement-popup.md §7d). `media_missing` covers type/mode/color/length/ID/XCVR/connector/speed; `ip_missing` covers network/VLAN/IP/GW/mask. Finer detail stays in `target_field`. **`other` + `target_field` is the fallback.**

**Status:** `open` (unworked) | **`deferred`** (held in the fill-later queue; `deferred_at`/`deferred_by` set; `note` kept and recommended) | **`resolved`** (the field is now set; `resolved_at`/`resolved_by` set) | `dismissed` (`note` required; same resolved columns). **Open and deferred both count as unresolved** for job flags (`job_has_open_items`, home counts, the fill-later queue). Re-opening is a new row (keeps history). There is **no item expiry**; audit is enough. No separate hold-reason enum: `note` is enough.

**Dedupe:** unique index among *unresolved* items
`uq_job_open_items_unresolved ON job_open_items (project_id, item_type, coalesce(epif_request_id,0), coalesce(device_id,0), coalesce(device_psu_assignment_id,0), coalesce(connection_id,0), coalesce(cable_id,0), coalesce(target_field,'')) WHERE status IN ('open','deferred')`.
A re-upload refreshes the note and `import_row_id` on the existing unresolved row and does not create a second one.

**Indexes / queue:**
- `ix_job_open_items_queue (project_id, status, item_type, created_at) WHERE status IN ('open','deferred')` — the job's fill-later list (filterable by open vs deferred).
- `ix_job_open_items_device_id`, `ix_job_open_items_cable_id`, `ix_job_open_items_import_row_id` (and the same for the other FKs) — group/join the list API.
- The list API **denormalizes display fields by join, never as stored copies**: `job_imports.filename` via `import_row_id`, `devices.host_name` via `device_id`, `cables.label` and `cables.trail` via `cable_id`. The FK indexes above are enough to group by file, then device or cable, then field. (A later `ix_cables_trail` is only needed if we search trails globally; not required for this list.)
- Cross-job queue ("anyone tracking jobs" = any tech or admin; **no assignee/watcher column**. "Assigned to me" is **parked under Later**):
  `SELECT … FROM job_open_items i JOIN projects p ON p.id = i.project_id WHERE i.status IN ('open','deferred') AND p.status = 'open' AND p.deleted_at IS NULL ORDER BY i.created_at`.

**Who can work them:** tech or admin may resolve, defer or dismiss (any signed-in user may read). Resolving writes the target field through the normal service in the same change_set, then marks the item `resolved`. Audit `job_open_item.create` / `.defer` / `.resolve` / `.dismiss`.

---

## 4. Job and import-batch tables (extensions of D73–D77)
`epif_imports` is generalized to **`job_imports`** (one row per uploaded file, ePIF or cable matrix). The earlier `epif_imports` shape is otherwise kept.

```
job_imports (
  id PK,
  project_id          INT NOT NULL FK projects RESTRICT,     -- always set: the job already exists
  dcreq               VARCHAR(12) NOT NULL,                  -- denormalized copy of the job's DCREQ (format CHECK)
  dcreq_reference_id  INT NOT NULL FK project_references RESTRICT,
  kind                VARCHAR(16) NOT NULL,                  -- ck IN ('epif','cable_matrix')
  filename, sha256, uploaded_by, uploaded_at,
  status              VARCHAR(12) NOT NULL DEFAULT 'review', -- ck IN ('review','committed','abandoned')
  change_set_id       INT NULL FK change_sets SET NULL,      -- set at commit
  ix_job_imports_project_id, ix_job_imports_dcreq, ix_job_imports_sha256)
import_rows (
  id PK,
  job_import_id       INT NOT NULL FK job_imports CASCADE,
  row_number          INT NOT NULL,                          -- 1-based data row
  raw_json            TEXT NOT NULL,                         -- the parsed cells (never secrets; iLO headers rejected, §6 of DEVICE_DATA_MODEL)
  result              VARCHAR(16) NOT NULL,                  -- ck IN ('ready','warning','held','conflict','committed','skipped')
  messages_json       TEXT NULL,                             -- [{code, field, message}]
  epif_request_id / device_id / connection_id / cable_id NULL,  -- filled at commit when a record is created
  uq_import_rows_job_import_id_row_number)
```

- Because the job is created **before** the upload, `dcreq` on the batch is **NOT NULL**. A missing DCREQ on a *CSV column* is irrelevant: the batch belongs to the typed job. D77 still holds for **row** fields (missing data never blocks commit).
- `epif_requests` (DEVICE_DATA_MODEL §5.6) gains `job_import_id` FK `job_imports` ON DELETE SET NULL, plus the existing request columns. `project_id` is copied from the job.

---

## 5. Stage, validate, commit
1. **Stage.** Parse the CSV (unknown headers = file error). **Secret or iLO credential headers reject the whole file** with **422 `import_forbidden_columns`**. The body is `{code, headers: [...]}` — **the offending header names only, never the values** (D10). **Nothing is staged or stored.** Insert `job_imports` + `import_rows` in one change_set (`source='csv_import'`) only after the file passes. No devices or connections yet. Status `review`.
2. **Validate** (in memory, maps preloaded once: racks by hall/row/name, profiles, hostnames-per-rack, serials, ports, live (port, lane) occupancy). Each row gets `result` + messages. **Warnings and held/missing never fail the batch.** Only a malformed file or a bad DCREQ already failed before this.
3. **Commit** (tech/admin, all-or-nothing for the *writable* rows, one change_set):
   - `ready` and `warning` rows write their records (devices / `epif_requests` / PSUs / cables / connections / hops) and open items for every warning.
   - `held` rows write **no** live device or connection (they cannot legally exist yet, e.g. an Install device with no rack — placement rule §0a). They stay as `import_rows` + an open item. That is still a successful commit of the batch.
   - `conflict` rows (unique collisions the DB would reject: hostname in that rack, serial, live (port, lane), RU overlap) are **not written**. They become open items of type `other` (or a future `conflict_*`) and the rest of the batch still commits (Q3).
   - Idempotent **re-upload** of the same file (matching `sha256` for that job and kind): reopen the existing batch in `review` if not committed; if already committed, only fill previously empty fields and refresh open items — never overwrite a later manual edit (warning `assignment_differs_from_import`). A new sha256 is a new batch on the same job.
4. **Audit:** `job_import.stage`, `.commit`, `.abandon`, plus the usual per-record audit under the same change_set.

Commit of a batch with only warnings and open items is **200** with `warnings[]` and `open_item_count`. It is never a 4xx because of missing data (D106).

---

## 5.1 `GET /home/summary` (data side)
The API response shape is Backend's (home.md). The data is this query outline (SQLite shown; PG uses `now() - interval '30 days'`):

```sql
-- current jobs
SELECT count(*) FROM projects
 WHERE status = 'open' AND deleted_at IS NULL;

-- open over 30 days (overdue)
SELECT count(*) FROM projects
 WHERE status = 'open' AND deleted_at IS NULL
   AND opened_at < datetime('now', '-30 days');

-- closed within 30 days (home workload tile; stays visible)
SELECT count(*) FROM projects
 WHERE status = 'closed' AND deleted_at IS NULL
   AND closed_at >= datetime('now', '-30 days');

-- unresolved items by type (on current jobs only)
SELECT i.item_type, count(*)
  FROM job_open_items i
  JOIN projects p ON p.id = i.project_id
 WHERE i.status IN ('open','deferred')
   AND p.status = 'open' AND p.deleted_at IS NULL
 GROUP BY i.item_type;
```

Optional detail lists (same predicates, `ORDER BY opened_at` / `closed_at DESC`, capped) feed the tiles. All four use the indexes in §2.1 and `ix_job_open_items_queue`.

## 5.2 Abandon (empty job after step 1)
The wizard creates the job at step 1, before any file. If the tech **cancels** after that, the job may be **hard-deleted** only when it is still **empty**:
- no `job_imports` with `status = 'committed'`;
- no `devices.project_id` or `cables.project_id` pointing at it;
- no `job_open_items` with `status IN ('resolved','dismissed')`.

**Staged** (`review` / `abandoned`) import rows and batches are **deleted first** in the same transaction (service-level; `job_imports.project_id` stays **RESTRICT**, no database cascade from the job onto history or devices). Unresolved skip-file items go with them. Then the primary DCREQ reference and the `projects` row are deleted.

**Who:** the **creator** (`projects.created_by`, or `opened` actor) **or an admin**. Anyone else gets 403. Audit `job.abandon` (snapshot first, same convention as other hard deletes). If the job is not empty, abandon returns **409 `job_not_empty`** and the job **must be closed** instead.

## 6. ePIF PSU1 / PSU2 and extra PSUs (Designer Q3)

Uses the PDU plan (D62–D68, D71), which is itself still planned. This intake **does not invent a second PSU model**.

- The ePIF Space & Power export has **PSU1** and **PSU2** columns. The value is **feed letter + port**, e.g. `A12` (D62). The PDU is **implied** by the device's own Row + Rack + feed, not by a free-text PDU name (`pdu_text` stays dropped).
- **`epif_psus`** is the **request-time record** (one row per PSU on that ePIF request):
  - `psu_index` 1 and 2 from the CSV (`source='csv'`).
  - PSU 3+ entered in the import review or later (`source='import_review'` or `'manual'`), when the device profile's **`psu_count`** is > 2 or the tech adds one. `psu_count` is recommended, not required to publish (D71); NULL means "assume 2."
  - `raw_value`, `pdu_feed`, `pdu_port`, `resolved_pdu_device_id` (FK devices SET NULL) as in PDU_SIDE_MOUNT_PLAN §10.4 / §11.
- **On import commit**, each parsed `epif_psus` row is **copied** into **`device_psu_assignments`** (the device's current state, D68) when the device row is created: `(device_id, psu_index, feed, pdu_port, resolved_pdu_device_id, source, assigned_at/by)`.
  - One live assignment per `(device_id, psu_index)`.
  - One device per PDU outlet (D69/D72, hard unique). A taken outlet is **not** written; the batch still commits and an open item `pdu_missing` / note `outlet_taken` is raised (warn-only, D63). Take-over/swap stay as in the PDU plan.
  - If the feed has no live side PDU in that rack: assignment is stored with `resolved_pdu_device_id` NULL and open item `pdu_missing`.
  - Unparsed values (`psu_unparsed`) and a missing PSU when `psu_count` says there should be one (`missing_psu`, `target_field='psu_N'`) are open items. `psu_count_mismatch` is a warning only.
- A later fill of an open PSU item goes through the normal PSU-assignment API (editable at any time, D69), then marks the item resolved. Move/unrack/decom still clear assignments (D68/D74).
- Until the PDU-plan tables land, ePIF intake can still **stage** PSU columns and open items, and defer writing `device_psu_assignments`.

---

## 7. Cable-matrix mapping (Designer Q4)
Maps to DEVICE_DATA_MODEL §3.4, §7 and §8. A row is one end-to-end **connection** (two endpoint ports) plus optional **hops** through panels and a **cable**.

| CSV / UI field | Lands in | Commit without it? |
|---|---|---|
| Action (add / remove / move) | `connections.action` (and status) | **Fill-later** (default `add` if blank; warning) |
| A and Z: Name (hostname) | resolve → `device_ports.device_id` | **Held** if both sides can't be resolved: no connection is written; open item `missing_hostname` / `unresolved` on the import row |
| A and Z: Row, Rack (and RU if present, for checks) | resolve the device (must match the named device's placement) | **Fill-later** if the name already uniquely resolves; **held** if name is ambiguous across halls (open item `unresolved_cabinet`) |
| A and Z: Slot, Port | `device_ports.slot`, `.name` (created behind the existing flag if missing) | **Held** if port is blank: open item `missing_port`, `target_field='port_a'` or `'port_z'` |
| A and Z: lane (breakout, optional) | `connections.port1_lane` / `port2_lane` (0 = whole port, §7) | **Fill-later**; default 0. A breakout row that names a panel front hop **derives** the lane from `rear_position` |
| Hop1–Hop7 (`panel:port`, e.g. `MPO-PNL-03:F2`) | `connection_hops(seq, port_id, lane, …)` in order | **Fill-later**. Missing or unresolved hops: the connection **is** still written (A↔Z), and an open item `unresolved_hop`, `target_field='hop_N'` is raised. A resolved hop that would violate one-device-per-(port,lane) (D72 / §7) is **not** written (conflict, Q3) |
| Trail | `cables.trail` | **Fill-later**, open item `missing_trail` |
| Cable type, mode, color, length, label, ID | `cables.*` / `external_id` | **Fill-later**. Duplicate live `label` → conflict on that row only |
| XCVR make/model, Connector, Speed (A and Z) | `device_ports.transceiver_*`, `.connector`, `.speed_mbps` | **Fill-later** |
| Network, VLAN, Native VLAN, IP, GW, Mask | `port_ip_config` | **Fill-later** (table may land with hops) |
| TAP | `device_ports.kind='tap'` | **Fill-later** |

**Required vs held, in one line:** a connection is committed only when **both endpoint ports** resolve to devices; everything else (hops, trail, media, IP, action) is fill-later and becomes an open item. That matches "missing data never blocks commit": the batch commits, and only the impossible rows stay in the queue.

Canonical port order (`port1_id < port2_id`) and one live (port, lane) are enforced as in §7. Decom keeps connections (D29 / PC1).

---

## 8. Conflicts with earlier decisions
| Earlier | This plan |
|---|---|
| **D76:** the import never creates a DCREQ or a project; unknown DCREQs stay unlinked text | **Superseded for job intake (D104/D105).** Typing a new DCREQ **creates the job and the reference**. The import still does not create them — it only attaches to the job that already exists. The app still does not invent ticket numbers. |
| D73 format, trim+upper | Unchanged. |
| D75: a project may have many DCREQs; each DCREQ is on one project | Unchanged. v1 creates exactly one (the primary). Attaching and extra DCREQs are later. |
| D77: a missing DCREQ never blocks commit | **Kept for row/field data (D106).** The *job* always has a DCREQ, because the user typed it before uploading. |
| Q-D2 (CSV project matching), Q-D4 (auto-link) | Q-D2 is answered for this flow (match/create by typed DCREQ). Q-D4 is moot on this path. |
| D11 create-only CSV; upsert later | Kept. Re-upload does not become a general upsert. |
| No secrets (DEVICE_DATA_MODEL §6) | Unchanged: iLO/password headers reject the file. |
| Held migrations `p1_30_project_dcreq`, `p1_31_device_project_indexes`, `p1_32_epif_import_dcreq` | **Expanded, same numbers, still held until Preston's go** (§9). |

---

## 9. Migration sequencing (proposed, held until go)
After whatever is head (today p1_27 on main; p1_29 if cabinet profiles have landed):
1. **`p1_30_project_dcreq`** (expanded): DCREQ format CHECK, `uq_project_references_dcreq`, `projects.status/opened_at/closed_at/closed_by/primary_dcreq_id`, the current-jobs index, backfill `opened_at = created_at` for existing projects (status `open`). Precheck: list existing `kind='DCREQ'` refs that fail the format after trim+upper, then abort. No silent rewrite.
2. **`p1_31_device_project_indexes`** — unchanged (Backend: `devices(project_id, status)`, `devices(updated_at)`).
3. **`p1_32_job_imports`** (renamed from `p1_32_epif_import_dcreq`): `job_imports`, `import_rows`. `epif_requests` / `epif_psus` if they have not landed yet.
4. **`p1_33_job_open_items`**.
5. **`p1_34_cable_matrix_rest`** if hops / trail / status / `port_ip_config` are still missing (DEVICE_DATA_MODEL §7). May merge with item 32 follow-up.
6. **`device_psu_assignments`** stays on the PDU-plan revisions; ePIF commit copies into them once they exist.

All new names follow the NC (short names or `op.f()`, no doubled `ck_` prefix). CHECKs and partial indexes use the same SQL on SQLite and PG. No `ON DELETE CASCADE` from a job onto devices or history (RESTRICT / SET NULL as above).

**Tests (when built):** format and uniqueness; 409 `job_exists`; current and overdue computed flag; open/deferred dedupe, deferred_at CHECK, and one-target CHECK; commit with warnings is 200; held rows create no device; re-upload is idempotent; PSU1/2 copy into assignments; cable row with only A/Z ports commits and hops become open items; 422 `import_forbidden_columns` (names only, nothing staged); abandon of an empty job vs 409 when not empty; `GET /home/summary` counts; admin/tech write, read-only users 403 on commit.

---

## 10. Notes for the Designer
Please write / keep `docs/design/job-intake.md` against these assumptions (all planned, not approved). Rev 2 answers your §10:

1. **The job key is the DCREQ** (`DCREQ0001234`). One job = one `projects` row with that primary DCREQ. The start screen is "type a DCREQ"; a new one creates the job; an existing one shows 409 "this job already exists" until attach-to-existing is designed. **No untitled jobs; no `missing_dcreq`.**
2. **Upload order:** ePIF, then cable matrix, both onto that job. The CSV does not create the job. Skipping a file leaves `epif_not_uploaded` / `cable_matrix_not_uploaded`, auto-resolved when that file is later committed.
3. **Missing data = warning + an open or deferred item, and the commit button stays enabled.** A success response can still list warnings and a fill-later count. Blocking at the start: a bad DCREQ format, **422 `import_forbidden_columns`** (secret/iLO headers; names only, never values; nothing staged), or a confirmed existing job.
4. **Fill-later queue** is unresolved `job_open_items` (`open` and `deferred`) for that job, plus a cross-job view of current jobs. Each item has a type, an optional target and **field name**, `note`, `deferred_by`/`deferred_at`, `resolved_by`/`resolved_at`. The list API **joins** filename, hostname and cable label/trail (not stored copies). Techs and admins work the queue; everyone signed in can see it. **No assignee.** "Assigned to me" is later. "Anyone tracking jobs" = any tech or admin.
5. **Job status is stored** (`open`/`closed`). Close and reopen are explicit audited actions (`job.close` / `job.reopen`), not derived from device state. **"Current"** = not closed. **"Overdue"** is computed from `opened_at` (open more than 30 days). **Closed jobs stay on the home tile for 30 days after `closed_at`** (a second computed rule). Closing is allowed with leftover unresolved items (warn). Home counts come from `GET /home/summary` (§5.1); the response shape is Backend's.
6. **PSU1/PSU2** in the ePIF file are `A12`-style values. Extra PSUs are added in review when `psu_count` > 2. They become the device's live `device_psu_assignments`. A taken outlet or a missing PDU is a warning, not a failed commit. Post-commit S&P flags become `space_power_flag` items.
7. **Cable rows** commit when both A and Z ports resolve; Hop1–7, trail, label, media (`media_missing`) and IP (`ip_missing`) are optional fill-later. A breakout is several rows that share a switch port on different lanes, with hops through an MPO panel (DEVICE_DATA_MODEL §7) — not a special widget.
8. No iLO password or other secret is stored; that column in the file rejects the upload (**422 `import_forbidden_columns`**, header names only).
9. **Abandon:** if the wizard is cancelled after step 1 and the job is still empty (no committed imports, devices, cables or resolved items; staged rows are removed), the creator or an admin may hard-delete it (`job.abandon`). Otherwise the job must be closed.
10. **No item expiry.** Audit events are: `job.create` / `.close` / `.reopen` / `.abandon`, `job_import.stage` / `.commit` / `.abandon`, `job_open_item.create` / `.defer` / `.resolve` / `.dismiss`.
11. Desktop only (D55) unless you are told otherwise.

## 11. Open questions for Preston

**Resolved from Preston’s 2026-11-11 intake direction (plan only; not a build GO):**
1. When the typed DCREQ already exists: **409 `job_exists` for v1** (attach comes later). Matches “a new DCREQ creates a new job; attaching comes later.”

**Still open:**
2. May a v1 job carry **additional DCREQs** besides the primary, or is that later only?
3. **Conflicts** the database would reject (hostname already in that rack, serial clash, RU overlap, one device per port): skip that row, warn, and still commit the rest (recommended), or stop the whole batch?
4. Who may **close** a job, and may they close it while open items remain (recommended: tech/admin, yes, with a warning)?
5. Does the **30-day clock** start when the DCREQ is typed (recommended) or when the first file is committed? Does reopen reset it (recommended: no)?

Also locked from that same direction (see docs/design/job-intake.md §9): one wizard for ePIF + cable matrix, and unresolved A/Z cable ends become fill-later open items. Build stays plan-only until he says go.
