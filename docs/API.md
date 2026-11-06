# DCIM API contract (v0.1)

Base URL in dev: `http://127.0.0.1:8000`. The full schema is in `apps/api/openapi.json`, and interactive docs are at `/docs`.

## Conventions
- JSON in and out. `PATCH` is partial: send only the fields you want to change.
- **Lists** take `limit` (1-500, default 50) and `offset` (default 0) and return a plain JSON array. The total count before paging is in the `X-Total-Count` response header (CORS exposes it). Results are ordered by `id`.
- `q` is a case-insensitive substring search.
- **Error shapes (exactly three):**
  1. **Plain string** `{"detail": "..."}`: used by most 401/403/404/409 errors, e.g. `"Device not found"` or the U-overlap and fit messages.
  2. **Coded object** `{"detail": {"code": "...", "message": "..."}}`: used only for `hostname_conflict` (409), `profile_type_mismatch` (422), `serial_conflict` (422), `password_change_required` (403), and `secret_field_not_accepted` when a CSV file is rejected (422). Branch on `code` and show `message`.
  3. **Validation list** (422 from request parsing; see below), plus a plain list of strings for password-policy failures (`/users`, `/auth/change-password`).
  Clients should handle `detail` being a string, an object with `message`, or a list. User-facing messages say "cabinet" for a rack; the field and path names stay `rack`/`rack_id`/`/racks`.
- Status codes: `404` (not found, including a missing parent or reference), `409` (conflict: duplicate name or serial_number, U overlap/out of bounds, deleting a parent that still has children, resizing gear that is in use), and `422` (validation).
- Validation errors (422) look like `{"detail": [{"type": "...", "loc": ["body", "field"], "msg": "..."}]}`. The submitted value is never echoed back.

## Resources
| Resource | Fields (bold = required on create) | List filters |
|---|---|---|
| `/sites` | **name** (unique), address, is_default | `q` |
| `/halls` | site_id (alias `building_id`; omitted = default site), **name** (unique per site) | `site_id` (alias `building_id`), `q` |
| `/rows` | **hall_id** (alias `room_id`), **name** (unique per hall), pos_x, pos_y, orientation | `hall_id` (alias `room_id`), `q` |
| `/racks` (cabinets) | **row_id**, **name** (unique per row), u_height (1-100, default **53**, the standard cabinet; existing cabinets keep their height), pos_x, pos_y, orientation; read-only `effective_orientation` | `row_id`, `hall_id` (alias `room_id`), `q` |
| `/device-types` | **manufacturer**, **name** (model; unique per manufacturer), u_height (default 1), is_full_depth (default true) | `manufacturer`, `q` (name or manufacturer) |
| `/devices` | **host_name**, status, serial_number (vendor serial or asset tag; unique when set), device_type_id, profile_id, rack_id, position_u, face, rack (legacy text label), descriptive fields below | `rack_id`, `device_type_id`, `status`, `unplaced` (`true` = not in a cabinet, `false` = in one), `owner`, `q` (host_name/serial_number) |
| `/cabinet-profiles` (admin writes) | **manufacturer**, **model**, name (variant, default "Standard"; manufacturer+model+name unique ignoring case), u_height, width/height/depth_mm, rack_unit_width, rail_type, rail depths, doors, usable dims, weight_capacity_kg, color_hex, notes. See "Cabinet profiles" below | `status`, `q` |
| `/device-types/{id}/profiles` | **name**, is_default, width_mm, height_mm, depth_mm, is_full_depth, faces, ports, power, model_refs (u_height always = the type's) | |
| `/groups` | **name** (managed-by group; unique case-insensitively → 409) | `q` |
| `/vendors` | **name** (unique case-insensitively) | `q` |
| `/contacts` | name, email (needs at least one; email unique case-insensitively, stored lower-case), phone, organization, vendor_id. **Contains PII** and is never in the device CSV | `q` |
| `/projects` | **name**, description, site_id (alias `building_id`), intake_id (unique when set), intake_date. DELETE is a soft delete | `q` (name/intake_id) |
| `/projects/{id}/references` | **kind** (`CHG | DCREQ | INC | OTHER`), **ref**; duplicate → 409. Lookup with `GET /project-references?kind=CHG&ref=CHG0001` | |
| `/projects/{id}/contacts` | **contact_id**, **contact_role** (`dc | vendor | other`), title; DELETE `/projects/{id}/contacts/{contact_id}?contact_role=` | |
| `/users` (admin) | **email**, **role**, display_name, temporary_password (omit to generate); PATCH role / is_active; `POST /users/{id}/reset-password`, `/unlock` | |
| `/audit-events` (admin, GET only) | append-only log: actor, action, entity, before/after, request id, `via` (api, script, migration, csv_import), `retention_class` (standard, or restorable = deletion snapshots, kept ≥ 24 months and excluded from the 13-month purge; `DCIM_RESTORABLE_RETENTION_MONTHS`) | see openapi |

Each resource has `GET` and `POST` on `/{resource}`, plus `GET`, `PATCH`, and `DELETE` (returns 204) on `/{resource}/{id}`. A parent's ID (for example `site_id`) cannot be changed with PATCH.

**Deleting devices and racks.** `DELETE` is admin-only and is a soft delete. Deleting a device sets it to `decom`, removes it from its rack, and hides it from list and get responses. Deleting a rack soft-deletes the rack and decommissions every device in it. `DELETE /devices/{id}?hard=true` returns **403** until hard delete is approved (`DCIM_HARD_DELETE_ENABLED`, default off). When hard delete is on, the device's full record, including its history, is saved in the audit log before the device is permanently removed.

**Profile-less device removal (items 47/48)** is an operator CLI only (`scripts/remove_profileless_devices.py`, `scripts/restore_from_audit.py`); there is no endpoint, and API hard delete stays 403. Its snapshots appear in `/audit-events` as `hard_delete` with `via=script`, `retention_class=restorable`. Exports go only to `DCIM_EXPORT_DIR` (see the README); their path and SHA-256 are recorded on the change set.

**Building/Room aliases and the default site.** A Building is a site and a Room is a hall. Request bodies and query strings accept `building_id`/`building` for `site_id`/`site`, and `room_id`/`room` for `hall_id`/`hall`. Responses always use the site/hall names. Sending both forms with different values returns 422. Sites have `is_default`, and exactly one site is the default (seeded as `Default`). A hall created without a site goes into the default site. Setting `is_default: true` on a site (on create or PATCH) moves the default to it. Deleting the default site, or setting its `is_default` to false, returns 409.

**Device descriptive fields.** These are all optional; only `host_name` is required: `description`, `notes`, `asset_type`, `eos_date` (YYYY-MM-DD, end of support), `app_service`, `system_type`, `system_type_confidence` (`high | medium | low | unknown`), `color_hex` (`#RRGGBB`), `power_assignment` (free text), `historic_name`, `project_id` (current project; unknown → 404; CSV column `project_intake_id`), and `owner` (free text, kept separate from the managed-by group; blank is stored as null; filter with `GET /devices?owner=` (exact, case-insensitive)). The read-only fields are `created_by` (the creating user's email), plus `effective_asset_type` and `effective_eos_date`, which fall back to the device type's `asset_type`/`eos_date`, and `effective_color_hex` (device, then profile). Device types gain optional `asset_type` and `eos_date`. There is no asset tag field. In CSV, an `asset_tag` header fills `serial_number`, and a row where both are present with different values is an error. CSV export includes all of these columns.

**effective_orientation** (racks, hall layout, elevation) is the rack's own `orientation`, or the row's when the rack's is null.

**Profile extras.** Profiles also have optional `color_hex` (`#RRGGBB`, the default device color), `airflow` (`front_to_rear | rear_to_front | side | passive`), and `power_type` (`AC | DC | AC_DC`). `ports` must be a list of `{name, kind?, connector?, speed_mbps? (>0, per port), face? (front|rear), ...extra keys}`. `power` must be a list of `{name, connector?, voltage?, max_draw_w?, typical_draw_w?, redundancy_group?, ...}`. Any other shape returns 422. A device's `effective_color_hex` is the device's `color_hex`, then its profile's (the selected or default profile). Dimensions and `u_height` cannot be overridden per device.

**Serial not accessible.** Devices have `serial_unavailable` (bool, default false) and `serial_note` (max 128 characters, e.g. "behind PSU"). `serial_unavailable: true` while `serial_number` is set returns 422 `{"detail": {"code": "serial_conflict", ...}}`; to switch, PATCH `{"serial_unavailable": true, "serial_number": null}`. The list filter `?missing_serial=true` returns devices **without a `serial_number`**, both those flagged `serial_unavailable` and those simply left blank (the UI's "No serial"). `?missing_serial=false` returns devices that have a serial. Both columns are in CSV import and export.

**Report filters and sort.** `GET /devices` and `GET /devices/export` share these filters: `site_id`, `hall_id` (alias `room_id`), `row_id`, `rack_id` (repeatable: `?rack_id=1&rack_id=2`), `status` (repeatable; unknown values return 422), `owner`, `project_id`, `missing_serial`, `q`. `sort` is a comma list of whitelisted fields (`host_name`, `status`, `serial_number`, `position_u`, `rack_id`, `device_type_id`, `owner`, `eos_date`, `created_at`, `updated_at`, `id`); a leading `-` sorts descending, and any other field returns 422. The default order is `id`. The export adds read-only `site`, `hall`, `row` and `cabinet` name columns, which import ignores.

**Name history.** Renaming a device (PATCH `host_name`) records `{old_name, new_name, changed_at, changed_by, change_set_id}`. `GET /devices/{id}/name-history` returns these, newest first. The device list's `q` also matches previous names.

**profile_id** on a device optionally picks a specific profile of its device type. Null means the type's default profile. A profile from another device type returns 422 `profile_type_mismatch`.

Device enums: `status` is one of `install | active | decom`, default **`install`**. **Behavior change:** the default was `active` before migration `p1_09_status_default_install`. Existing rows are unchanged, and CSV rows without a status also become `install`. `face` is `front | rear` (default `front`).

## Auth and roles
- `POST /auth/login` `{email, password}` sets an HttpOnly session cookie and returns `/auth/me` (`id, email, display_name, role, must_change_password, csrf_token`). Other endpoints: `POST /auth/logout`, `GET /auth/me`, `GET /auth/providers` (public), and `POST /auth/change-password` `{current_password, new_password}`.
- Every unsafe request (POST/PATCH/DELETE) needs the `X-CSRF-Token: <csrf_token>` header and a same-origin `Origin`. Missing either one returns 403. A request without a session returns 401.
- Roles (deny by default):
  | Action | admin | technician | read-only |
  |---|---|---|---|
  | GET anything (except below) | yes | yes | yes |
  | `/users`, `/audit-events` | yes | no | no |
  | Create/patch devices, CSV import, create device types and profiles | yes | yes | no |
  | Move a cabinet (PATCH `/racks/{id}` with only `pos_x`, `pos_y`, `orientation`) | yes | yes | no |
  | Create/patch/delete sites, halls, rows, cabinets; delete devices; patch/delete device types and profiles | yes | no | no |
  Wrong role → 403; no session → 401.
- `must_change_password` users get 403 `password_change_required` on everything except `/auth/me`, `/auth/logout` and `/auth/change-password`. A successful change rotates the session (a new cookie and new `csrf_token`) and signs out the user's other sessions.
- First admin: `python -m app.scripts.create_admin --email you@example.com` (see apps/api/README.md). There are no default users. Dev-only demo logins come from `scripts/seed_demo.py`.
- All configuration uses `DCIM_` environment variables (the full table is in apps/api/README.md).
- Login rate limits (per process): 10 attempts per minute per IP, 5 failures per minute per IP+email, and 300 per minute overall. Going over returns **429** with `Retry-After` (seconds). These are configurable with `DCIM_LOGIN_RATE_PER_IP`, `DCIM_LOGIN_FAILURES_PER_IP_EMAIL`, `DCIM_LOGIN_RATE_GLOBAL`, and `DCIM_LOGIN_RATE_WINDOW_SECONDS`, where 0 disables a limit. Per-account lockout (`DCIM_LOGIN_MAX_FAILURES`, `DCIM_LOGIN_LOCKOUT_MINUTES`) still applies.

## No credentials
DCIM never stores passwords or secrets (D10). Request bodies and CSV headers are checked against a block list. Names are normalised first: camelCase is split, letters are lower-cased, and runs of spaces, hyphens or punctuation become `_`. So `iLO password`, `ILO PW`, `ilo_pw`, `ilo-password`, `BMC Password` and `iLOPassword` are all caught. A name is blocked when any word is `password`, `passwd`, `pwd`, `pw`, `pass`, `passphrase`, `secret`, `token`, `community`, `credential(s)`, `apikey` or `privatekey`; when it contains the adjacent words `api key`, `private key`, `access key` or `secret key`; or when the joined name contains `password`, `passwd`, `apikey` or `privatekey`. Words such as `passive`, `bypass` and `secretary` are allowed. A body containing one of these returns 422 with `detail[0].type = "secret_field_not_accepted"`, and the field name appears in `msg` but the value never does. A CSV with such a header is rejected as a whole with 422 `{"detail": {"code": "secret_field_not_accepted", "message": ...}}`. Declared fields such as `/users` `temporary_password` and the auth endpoints are not affected.

**Response security headers.** Every response (including a 400 from the trusted-host check) carries CSP, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, `X-Frame-Options: DENY`, `Cache-Control: no-store` (unless set) and `Permissions-Policy: camera=(), microphone=(), geolocation=()`. `DCIM_PERMISSIONS_CAMERA_SELF=true` changes the camera part to `camera=(self)`. `Strict-Transport-Security` is sent only when `DCIM_HSTS_ENABLED=true` **and** the request is HTTPS: `max-age=DCIM_HSTS_MAX_AGE` (default 86400), plus `; includeSubDomains` when `DCIM_HSTS_INCLUDE_SUBDOMAINS=true` (default off).

## Hall floor plan
- Rows and racks have optional `pos_x` and `pos_y`, which are integer grid cells (≥ 0, units are up to the client), and an optional `orientation` of `N | E | S | W`, the direction the **front** faces. All three default to `null`.
- Halls have optional floor-plan hints. `aisle_axis` (`x | y`) is the grid axis the center aisle runs along (`y` = a vertical aisle), and `odd_side` (`low | high`) is the side of that aisle holding the odd-numbered rows (`low` = the smaller coordinate). Both default to `null` (no hint). The demo seed uses `y`/`low`. Rows have only their own `orientation`. Racks also return `effective_orientation`.
- Two racks in the same hall cannot have the same (`pos_x`, `pos_y`). The API returns 409: `Floor position (1, 1) in this hall is taken by cabinet 'R1'`. Rows are not checked.
- `GET /halls/{id}/layout` returns the hall, its rows, and their racks in one call (ordered by id):
  ```json
  {"id": 1, "site_id": 1, "name": "A", "aisle_axis": "y", "odd_side": "low",
   "rows": [{"id": 1, "hall_id": 1, "name": "1", "pos_x": 0, "pos_y": 2, "orientation": "E",
             "racks": [{"id": 1, "row_id": 1, "name": "R1", "u_height": 53, "pos_x": 0, "pos_y": 2,
                        "orientation": null, "effective_orientation": "E",
                        "device_count": 2, "u_used": 3, "u_free": 50}]}]}
  ```
  `u_used` is the total U height of mounted devices. Half-depth devices that share a U on the front and rear both count.

## Rack elevation
`GET /racks/{id}/elevation` returns 404 if the rack doesn't exist. Otherwise it returns the rack and the devices mounted in it, sorted by `position_u` and then `id`:
```json
{"id": 1, "row_id": 1, "name": "R1", "u_height": 53, "u_used": 3, "u_free": 50,
 "devices": [{"id": 7, "host_name": "web-01", "status": "active", "serial_number": null,
              "position_u": 1, "top_u": 2, "face": "front",
              "device_type": {"id": 2, "manufacturer": "Dell", "name": "R750",
                              "u_height": 2, "is_full_depth": true}}]}
```
`top_u` = `position_u + device_type.u_height - 1`. `u_used` and `u_free` follow the same rule as the hall layout. Unracked devices are not listed.

## Rack placement rules (devices)
- A device is placed when `rack_id` is set. Placement also requires `position_u` (the lowest U it occupies, 1-based); sending one without the other returns 422.
- **A profile is required for placement** (Preston; this **reverses the p1_08 "Unknown type" placement**). Send `profile_id`, or a `device_type_id` whose default profile is published, in which case the device stores that profile's id. `device_type_id` is filled in from the profile, and a different explicit type returns 422 `profile_type_mismatch`. Fit and overlap use the profile's `u_height` and `is_full_depth`. Errors on POST, PATCH and CSV import:
  - 422 `{"detail": {"code": "profile_required", "message": "Placing a device in a cabinet requires a profile ..."}}` when there is no profile.
  - 422 `{"detail": {"code": "profile_not_published", "message": "...", "missing": ["width_mm", "power_type", ...]}}` when the profile isn't usable. **Interim rule:** until the profile lifecycle (`p1_17`) lands, "published" means *complete*: `name`, `u_height` ≥ 1, `width_mm`, `height_mm`, `depth_mm` and `power_type`. `mounting` and a front image join the list with `p1_17`.
  - Setting or changing `profile_id` on any device, placed or not, needs a published profile too.
  - Unplaced devices may have no profile (only `host_name` is required). Unplace and decom keep `profile_id`.
- Deleting a profile that any device uses (placed, unplaced or soft-deleted) returns 409 `profile_in_use`; a profile that a newer version supersedes returns 409 `profile_superseded` (retire it instead). Since `p1_18`, `devices.profile_id` is NOT NULL (FK RESTRICT).
- **`needs_review` / `needs_review_reason`** (read-only, `p1_14`). Migrations and admin scripts set these flags; the API and CSV never set them. Reasons are `placed_without_profile` (an old typeless placement, still counted as 1U blocking both faces until it's removed), `profile_not_published` and `other`. Filter with `GET /devices?needs_review=true`; the flags also appear in `/devices/export` and in elevation device items. A flagged device accepts only:
  - unplace (`rack_id: null`)
  - decom
  - `profile_id` set to a published profile of the same type

  Any other PATCH returns 409 `{"detail": {"code": "<reason>", "message": ...}}`. A successful fix clears the flag.
- The device occupies `position_u` through `position_u + device_type.u_height - 1`. If that goes past `rack.u_height`, the API returns **409**, for example: `Device does not fit: U9-U11 exceeds cabinet 'R01' height of 10U`.
- **Overlap** means the U ranges intersect and either (a) both devices are on the same face or (b) either device type is full-depth. The API returns **409**, for example: `Placement U2-U3 (front) in cabinet 'R01' overlaps device 'web-01' (id 1) at U1-U2 (front)`.
- To unrack a device, PATCH `{"rack_id": null, "position_u": null}`.
- Host names are unique **per cabinet** (case-insensitive, live racked devices only); the same name may exist in other cabinets or unplaced. A clash returns **409** with `{"detail": {"code": "hostname_conflict", "message": "Host name 'web-01' already exists in cabinet 'R01'"}}`. Some errors put an object in `detail`, so read `detail.message` when `detail` is not a string.
- Shrinking a rack below its highest occupied U returns 409. Changing a device type's `u_height` or `is_full_depth` while devices use that type returns 409.

- **DB-level enforcement (P1-10, migration `p1_23_device_ru_slots`).** Table `device_ru_slots (rack_id, u, side)` (PK) holds one row per U per side a racked device blocks, using the same rule as the check above (full-depth = `front` and `rear`, otherwise the device's face; 0 U = none). It's derived: the server rewrites a device's slots in the same transaction whenever its `rack_id`, `position_u`, `face` or `profile_id` changes (create, PATCH/move, CSV import, adopt, decom, soft delete, rack delete). Two concurrent writers that both pass the Python check can't both commit: the second gets **409** `{code: "ru_slot_taken", message}`. Placement writes must go through the ORM (a Core/bulk `UPDATE devices` skips the slot sync), and rack height is not a DB check (it stays in the Python fit check). No API field or endpoint changes. Raw SQL writers must keep the slots in sync themselves.
- **`racks.hall_id` (P1-10, migration `p1_24_rack_hall_id`).** Rack responses carry a read-only **`hall_id`** (= its row's hall, set by the server; the composite FK `(row_id, hall_id) → rows(id, hall_id)` keeps them equal). The floor rule "one live rack per (pos_x, pos_y) in a hall" is now also a DB unique index (`uq_racks_hall_id_pos_x_pos_y`, live racks only); the API still answers 409 with its plain-string message first; a concurrent writer that slips past it gets **409** `{code: "floor_position_taken", message}` from the index.
- **History backfill (P1-10, migration `p1_25_device_history_backfill`).** Every device without status history got one `device_status_history` row (`from_status: null`, `to_status` = current status, `reason: "p1_25 backfill"`, one `change_sets` row with `source: "migration"`).
- **Placement-history baseline (migration `p1_26_placement_history_backfill`).** Every placed device with no placement history got one `device_placement_history` row (`from_*: null`, `to_*` = current rack/U/face, `reason: "p1_26 backfill"`, `changed_by: null`, `changed_at` = the device's `updated_at`, one `change_sets` row with `source: "migration"`). Devices themselves are unchanged.

## Profile catalog: `GET /profiles`
A flat, paginated list of every device-type profile, for the palette and for reports. Any signed-in role can read it. Results come from one joined query; image bytes are never included.
- **Filters:** `device_type_id`, `q` (profile name, manufacturer or model), `manufacturer` (exact, case-insensitive), `asset_type`, `status` (repeatable: `draft|published|retired`), `in_use=true|false`.
- **Sort:** `sort=manufacturer,model,name` (default). Fields are `id`, `name`, `manufacturer`, `model`, `u_height` and `device_count`; a leading `-` means descending, and any other field returns 422.
- **Paging:** `limit`/`offset`, with the total in `X-Total-Count`.
- **Item fields:** `{id, name, device_type_id, manufacturer, model, u_height, is_full_depth, width_mm, height_mm, depth_mm, power_type, airflow, asset_type, effective_asset_type, color_hex, is_default, status, device_count, front_image: {url, thumb_url} | null, front_image_url (deprecated alias, null)}`.
- **Interim `status`:** until `p1_17_profile_template` adds a real status column, `published` means complete for placement (dimensions, `power_type`, `u_height` ≥ 1) and everything else is `draft`. No profile is `retired` yet.
- `front_image` stays `null` until profile images (`p1_15`) ship.

## Connections (v1)
A baseline subset of DB item 11. It has device ports, cables (types `RJ45`, `LC`, `DAC`), and a connection between exactly two ports. **A connection has no status column.** The client derives it from the two end devices: if either end is `decom` it is **decom**; otherwise if either end is `install` it is **install**; otherwise **active**. The server returns this as `derived_status`. Not built yet: patch-panel paths (hops), breakout lanes, and connection history beyond audit events.

**Rules**
- One connection per port.
- A port can't connect to itself. Two different ports on the same device are allowed.
- Both ends must be live (not deleted) devices. Only endpoint ports can be connected.
- `DELETE /connections/{id}` removes the record and frees both ports. Its cable is deleted with it (cables have no status in v1), so the label can be reused.
- **Decommissioning a device keeps its connections.** This is the v1 rule. What decom should do to connections is **pending Preston's decision (PC1)**, and P2 item 14 ("decom removes connections") is not applied. They show as `decom` until someone deletes them, so they can be traced before the cables are pulled. Soft-deleting a device also keeps them.
- Cable labels are unique, case-insensitive. `cable_type` is limited to `RJ45`, `LC` and `DAC`, enforced by a DB CHECK and the API. Ports also carry `lanes`, `rear_port_id` and `rear_position` columns for future panels and breakouts. v1 ignores them, and every connection uses lane 0. A clash returns 409 `{"code":"cable_label_conflict"}`.

**Endpoints.** Every role can read and export. Admin and technician can write.
| Method | Path | Notes |
|---|---|---|
| GET | `/devices/{id}/ports` | `[Port]`, where Port = `{id, device_id, name, slot, kind, role, connector, speed_mbps, transceiver_make, transceiver_model, face, connection_id}`. `connection_id` is null when the port is free. |
| POST | `/devices/{id}/ports` | `{name, slot?, kind?, connector?, speed_mbps?, transceiver_make?, transceiver_model?, face?}`. `kind` is one of `ethernet, fiber, console, mgmt, power, tap, patch, other`. A duplicate name (case-insensitive, per slot) returns 409 `port_name_conflict`. |
| GET | `/devices/{id}/connections` | `[{connection_id, local_port {id,name,slot}, far_device {id, host_name, rack_id, cabinet, hall, position_u, face, status}, far_port {id,name,slot}, cable {id, cable_type, label, color, length_m} or null, local_status, far_status, derived_status, notes}]` |
| GET | `/connections` | `[Connection]`, paginated (`limit`/`offset`, `X-Total-Count`). Filters: `hall_id` (alias `room_id`), `row_id`, `rack_id` (repeatable; matches when **either** end is in it), `device_id` (either end), `cable_type` (repeatable), `derived_status` (repeatable), `cross_cabinet=true`, and `q` (host name, port name, or cable label). |
| GET | `/connections/export` | CSV with the same filters. Columns: `id, a_device_id, a_host_name, a_port, a_hall, a_row, a_cabinet, a_ru, a_face, b_… (same), cable_label, cable_type, cable_color, cable_length_m, a_status, b_status, derived_status, notes` |
| GET | `/connections/{id}` | `Connection` |
| POST | `/connections` | `{a_device_id, a_port_id or a_port_name, b_device_id, b_port_id or b_port_name, cable_type?, cable_label?, cable_color?, cable_length_m?, notes?}`. A port given by `*_port_name` that doesn't exist yet is created. Busy port: 409 `{"code":"port_in_use", "message", "connection_id"}`. Same port on both ends: 422 `self_connection`. Unknown device or port: 404. |
| PATCH | `/connections/{id}` | Cable and notes fields only. To re-point an end, delete the connection and create a new one. |
| DELETE | `/connections/{id}` | 204 |

`Connection` = `{id, a: End, b: End, cable, derived_status, notes, created_at}`, where End = `{device_id, host_name, status, rack_id, cabinet, hall_id, hall, row, position_u, face, port_id, port_name, slot}`. **`a`/`b` are in canonical order (lower port id first), not necessarily the order you sent.** Use `/devices/{id}/connections` for a "this device first" view. Audit events: `connection.create`, `connection.update`, `connection.delete` and `connection.port.create`.

## CSV
- `GET /devices/export` returns `text/csv` and takes the same filters as the device list. The columns are `id, host_name, status, serial_number, manufacturer, model, device_type_id, profile_id, rack_id, position_u, face, rack`, plus the descriptive columns and `created_by`. `id` and `created_by` are ignored on import.
- `POST /devices/import?dry_run=true|false` takes a raw CSV body with `Content-Type: text/csv`. `dry_run` defaults to **true**. The import accepts the export headers; only `host_name` is required. `manufacturer` + `model` look up `device_type_id` when it is blank. Rows are checked in order, so rows in the same file can conflict with each other.
  The response is `{dry_run, total_rows, created, errors: [{row, errors: [str]}]}`, where `row` is the file line number and the header is line 1. **All-or-nothing:** if any row has an error, nothing is saved and `created` is 0.

## Misc
`GET /health` returns `{"status":"ok"}`. `GET /version` and `GET /` also exist.

## Profile images (p1_15)

Images are stored in the database (`profile_images`, one original plus derived WebP variants per profile and face: a 512 px `thumb` and a 1024 px `tex` for 3D textures, both regenerated from the original on upload/replace and on `swap_faces` clones, never uploaded directly and never upscaled). JSON never includes the bytes, only URLs.

| Method | Path | Role | Notes |
|---|---|---|---|
| GET | /device-types/{tid}/profiles/{pid}/images | any | Metadata for each face (content_type, byte_size, width_px, height_px, sha256, version, etag, url, thumb_url, tex_url) |
| PUT | /device-types/{tid}/profiles/{pid}/images/{front\|rear} | admin, technician (draft); admin only on published | Raw body (no multipart) with Content-Type image/png, image/jpeg or image/webp. 201 created / 200 replaced. Optional If-Match (etag) → 412 `image_changed` |
| DELETE | /device-types/{tid}/profiles/{pid}/images/{face} | admin, technician (draft); admin only on published | 204 |

**F-3: images on published profiles.** On a `published` profile only an admin may upload, replace or delete an image. Anyone else gets **403** `image_change_requires_admin` (a technician can still change images on drafts; cloning to a new draft version is admin-only already). Every image change is audited with metadata only: `profile_image.create` / `.replace` / `.delete` on entity `profile`, actor from the session, and `after = {profile_id, face, profile_status, old_sha256, new_sha256, byte_size, (width_px, height_px,) change_set_id}`. Images copied by clone are recorded as `profile_image.create` on the new profile with `copied_from_profile_id`.
| GET | /profile-images/{pid}/{face}?variant=original\|thumb\|tex&v= | any (logged in) | ETag/If-None-Match → 304, Last-Modified, `X-Content-Type-Options: nosniff`, `Content-Security-Policy: default-src 'none'; sandbox`. Cache-Control is `private, max-age=300, must-revalidate`, or `private, max-age=31536000, immutable` when `v` is the current content version (the 16-hex sha256 prefix that every JSON image URL carries as `?v=`; a shorter or stale `v` gets the short cache). Each variant has its own ETag (its own sha256) and its URL carries its own `v`. `tex` gets the same re-encode/metadata stripping and headers as `thumb` |

Hardening:
- The body is capped while it streams: more than 2 MiB → 413 `image_too_large`; empty → 422 `image_empty`.
- The type is checked from magic bytes: not allowed → 415 `image_type_not_allowed`; differs from Content-Type → 415 `image_type_mismatch`.
- Dimensions are checked from the header before decoding: over 4096 px per side or 16 MP → 422 `image_too_big`.
- Animated → 422 `image_animated`; undecodable → 422 `image_invalid`.
- The image is re-encoded with EXIF orientation applied and all metadata stripped (EXIF, ICC profile, PNG text chunks; F-1).
- Uploads are limited to 30 per user per minute → 429 with Retry-After.
- At most `DCIM_IMAGE_DECODE_CONCURRENCY` (4) decodes run at once per API process; a request that waits longer than `DCIM_IMAGE_DECODE_WAIT_SECONDS` (10) → 503 `image_busy` with Retry-After (F-2).
- The audit log records metadata only (sha256, size, dimensions).

Image references all use one schema, **`ProfileImageRef`** `{url, thumb_url, tex_url, width_px, height_px, etag} | null` (width/height of the original; `tex_url` is the 1024 px WebP for 3D textures, or the original URL for an image that predates `p1_22_profile_image_tex` and hasn't been backfilled yet (`python scripts/regenerate_image_variants.py --execute`, idempotent, originals untouched); `etag` is the quoted sha256 that GET returns). They appear as `front_image` / `rear_image` on profiles, as `front_image` / `rear_image` (plus the deprecated `front_image_url`) on GET /profiles, and as `effective_front_image` / `effective_rear_image` (the device's profile front/rear image, `null` when missing) on devices, elevation devices and `/rows/{id}/front` items. Both come from the same image query, so the query count doesn't grow. Elevation devices also expose `effective_asset_type`.

## Asset types (p1_16)

`asset_type` on device types and devices is a fixed list of 11: server, switch, patch_panel, pdu, router, firewall, storage, blank, shelf, cable_manager (added in `p1_20`), other. NULL means unknown, and a device with NULL inherits its type's value (`effective_asset_type`). Other values → 422. The migration normalises existing free text (case, spaces, a few synonyms); anything it can't map becomes `other`. Nothing is deleted.

## Profile lifecycle and D36 (p1_17)

A profile is `draft` → `published` → `retired`. Existing profiles became drafts; nothing is grandfathered.
- Every profile read (`/device-types/{tid}/profiles…`, `GET /profiles`) includes `status`, `published_at`, `retired_at`, `mounting` (rack_19in, rack_23in, shelf, zero_u, other), `weight_kg` (optional, > 0 and ≤ 2000), and `readiness: {ready, missing[]}`. Publishing requires name, the type's asset_type, u_height, width_mm, height_mm, depth_mm, mounting, power_type, a front image **and a rear image** (rear required since 2026-10-24; `missing` lists `rear_image`, and publish returns 422 `profile_not_ready` with it). Profiles published before that rule and lacking a rear image **stay published** (nothing is changed or unpublished); their `readiness` reports `ready: false, missing: ["rear_image"]`. The demo seed (and a re-seed or upgrade) uploads a labeled DEMO rear image for every demo profile.
- **`usable` (computed, no stored state).** Every profile read (`/device-types/{tid}/profiles…`, `GET /profiles`) has `usable` (bool), `usable_issues` (every reason: `profile_draft`, `profile_retired`, `<field>_missing` such as `rear_image_missing` or `orientation_missing`; empty when usable) and `usable_issue` (= `usable_issues[0]`, or null). `usable_issues` is in priority order: `profile_draft`/`profile_retired` first, then `rear_image_missing`, then `orientation_missing`, then any other `<field>_missing`; `readiness.flags` uses the same order. The `?usable=` filters and the device-create refusal use this one rule (`usability()` in `device_types/lifecycle.py`). A profile is usable when it is published **and** its readiness is complete; `status` stays `published` either way. Using a published-but-unusable profile for a **new** device or a **profile switch** returns one code, **422 `profile_not_usable`** `{code, profile_id, reason (= issues[0]), issues[], message, missing[]}`: `POST /devices`, `POST /racks/{id}/devices`, `PATCH /devices/{id}` setting a different `profile_id`, a `device_type_id` that resolves to an unusable default profile, `POST /profiles/{id}/adopt`, and CSV rows (per-row `details[] = {code: "profile_not_usable", message, …}`). Devices already on the profile are not touched: no flags, no unplacing, and PATCHes that don't switch profile (including moves) keep working. `GET /profiles?usable=true` and `GET /device-types/{tid}/profiles?usable=true` return only usable profiles (use it for the palette); `usable=false` only unusable ones; omitted = all. Adding the missing image makes the profile usable again immediately.
- **Model asset type.** `asset_type` lives on the model (device type), from the 11-value list. A model with a NULL `asset_type` can't have a published profile: `readiness.missing` contains `asset_type` and `readiness.messages.asset_type` says to set it on the model. `PATCH /device-types/{id}` is admin + technician, but a technician may change **only** `asset_type` (anything else → 403 `device_type_change_requires_admin`); an invalid value → 422. The add-profile call `POST /device-types/{id}/profiles` takes an optional `asset_type`: it is set on the model when the model has none, accepted when equal, and 409 `asset_type_mismatch` when it differs. `readiness` is `{ready, missing[], messages{}, flags[]}` everywhere; `flags` lists the issues of an already-published profile (e.g. `rear_image_missing`), empty for drafts.
- `POST /device-types/{tid}/profiles/{pid}/publish` and `POST /profiles/{pid}/publish` (admin): 422 `profile_not_ready` with `missing[]` and `messages{field: text}`, 409 `profile_retired`; publishing an already-published profile is a no-op. Publishing clears `profile_not_published` flags on the devices that use the profile.
- Once published: PATCH of template fields (width/height/depth_mm, is_full_depth, mounting, power_type, weight_kg, faces) → 409 `profile_published` with `fields[]`. Cosmetic fields stay editable. Deleting the front or the rear image → 409 `profile_published`. The type's u_height/is_full_depth are frozen and its asset_type can't be cleared.
- **D36:** creating a device (POST /devices, CSV) needs a published profile, given as `profile_id` or a `device_type_id` whose default profile is published. Otherwise 422 `profile_required`, or `profile_not_published` with `profile_id`, `profile_status` and, when the type has one, `published_profile_id`. Placing a device or changing its profile has the same rule. Unplace/decom keep a draft profile.
- **CSV import** stays all-or-nothing. Each row error now also has `details: [{code, message, …}]`. Codes: profile_required, profile_not_published (+profile_id, profile_status), formula_not_allowed (+column), invalid_value (+column), unknown_device_type, unknown_project, alias_conflict, serial_conflict, and the placement codes (e.g. overlap). `errors: [str]` is kept.
- **Migration data step (PD5):** devices with a type but no profile (placed or not) are linked to the type's default profile and flagged `profile_not_published`. Placed devices with no type are flagged `placed_without_profile`. Nothing is deleted.

## Profile orientation (D58, migration p1_21_profile_orientation)

- Field `orientation` on device-type profiles: `port_front` | `power_front` | null. DB CHECK `ck_device_type_profiles_orientation`. Writable with `PATCH /device-types/{tid}/profiles/{pid}`; invalid values → 422.
- **Publish rule:** required only when the type's `asset_type` is `switch`. Publishing a switch profile without it → 422 `profile_not_ready` with `missing: ["orientation"]` and a `messages.orientation` hint. A switch profile that was published before it had an orientation stays `published`. It is not usable, though: `usable_issues` includes `orientation_missing`, and new placements get 422 `profile_not_usable`.
- **Edits on a published profile:** a NULL orientation may be filled at any time, even while devices use the profile. Changing a non-null orientation is allowed while no device uses the profile. Once it is in use → 409 `profile_published` (`fields: ["orientation"]`); clone with `swap_faces` instead. Two profiles of one type may share an orientation.
- `POST /profiles/{id}/clone {name?, swap_faces?}`: `swap_faces: true` flips the orientation and copies the original front image as the new rear and the original rear as the new front, regenerating the derived variants. The default name is "<name> (power front)" / "(port front)", and an existing suffix is replaced, not stacked. Names are capped at 128 characters; on a case-insensitive clash the clone gets " 2", " 3" and so on. The clone's audit records `cloned_from` and `swap_faces`.
- Exposed as `orientation` on profile reads, `GET /profiles` (filter `?orientation=port_front|power_front`), Device payloads (read-only, from the profile), rack elevation and row-front items, and the CSV export.
- **CSV import column `orientation`:** if `profile_id` is blank, the importer picks the type's published profile with that orientation (the default profile first, then the lowest id). If no published profile of the model has that orientation → per-row `orientation_not_found`. If the column is blank and the model has published `port_front` **and** `power_front` profiles → per-row `orientation_required`. An invalid value → `invalid_value`. If `profile_id` is given with a different orientation → `orientation_mismatch`.
- Not in scope: per-device intake/exhaust.

## Row front view

`GET /rows/{row_id}/front` (any role) → `{id, hall_id, name, orientation, racks: [RackElevation]}`. Live cabinets are ordered by pos_x, pos_y (unset last), then name. Each rack has the same shape as `/racks/{id}/elevation`. The response is built in a fixed number of queries regardless of cabinet or device count (no N+1). Items in both views carry effective_front_image, serial_unavailable, serial_note, profile_id, effective_asset_type, needs_review, needs_review_reason and `connection_count`. They also carry, from the device's **profile** (no new columns), `is_full_depth` (bool; true when there's no profile), `mounting` (`rack_19in`, `rack_23in`, `shelf`, `zero_u`, `other` or null) and `depth_mm` (number or null), `weight_kg` (number or null), plus `manufacturer` and `model` (the device type's manufacturer and name). Owner and managed-by are intentionally not on these items.

`face` (`front` | `rear`) is the side the device is mounted from. A **full-depth** device occupies its U on both faces whatever its `face`. A **half-depth** device (`is_full_depth=false`) occupies only its `face`, so a front and a rear half-depth device can share a U; a rear-mounted device has `face=rear`: its front panel faces the rear aisle, so the rear view shows its `effective_front_image`, and `depth_mm` measures from the rear rails. From the opposite aisle, a full-depth device shows its `effective_rear_image` (null → client fallback); a half-depth one isn't visible.

## Drag-to-rack placement

`POST /racks/{rack_id}/devices` (admin, technician), body `{host_name, profile_id, position_u, face?, status?, serial_number?, serial_unavailable?, serial_note?, descriptive fields…}` → 201 Device. It builds the same `DeviceCreate` as `POST /devices` (with `rack_id` from the path) and runs the same create path, so fit, overlap, the D36 profile rule, serials, history and audit are identical. 404 for a missing or deleted cabinet. `POST /devices` and `PATCH /devices/{id}` are unchanged.

## Profile versions, retire, adopt and fit-check (items 41/42, migration p1_17b_profile_versions)

Profiles gain `version` (≥ 1), `supersedes_profile_id` (FK to self, RESTRICT) and `published_by`.
- PATCH of fit fields (is_full_depth, width/height/depth_mm, mounting) that already have a value, on a profile used by any non-deleted device → 409 `profile_in_use {device_count, fields}`, even while it is a draft. Published profiles are frozen anyway (`profile_published`).
- `POST /profiles/{id}/clone {name?}` (admin) → 201 new **draft**. It copies fields and images, sets version = highest version for the type + 1 and `supersedes_profile_id` = id, and is not the default. The default name is "<name> v<version>". Name clash → 409 `profile_name_conflict`.
- `POST /profiles/{id}/retire` (admin): published → retired (`retired_at`). Devices already on it keep it. New devices, placements or profile changes to it get 422 `profile_not_published` (profile_status 'retired'). Publishing it again → 409 `profile_retired`.
- `POST /profiles/{id}/adopt {device_ids[] | all:true}` (admin, technician) moves devices onto this published profile. `all` means every device on the profile it supersedes. Each device goes through the normal PATCH path, so fit, overlap, flags, history and audit all apply, under one change_set. It is all-or-nothing: 409 `adopt_conflict {conflicts:[{device_id, host_name, code, message}]}` and nothing changes. A different device type → conflict `profile_type_mismatch`. Unknown ids → 404 `device_not_found`.
- `POST /racks/{id}/fit-check {profile_id, position_u, face?, device_id?}` (any role) → `{fits, conflicts:[{status, code, message…}]}`. It runs exactly the placement validation and writes nothing. Pass `device_id` to ignore a device's own slot when it is the one being moved.

## CSV import performance (item 9)

Import is still create-only, all-or-nothing, with `dry_run`. Serials (including soft-deleted) and device types are preloaded once. Unplaced rows are inserted in batches of 1000 under one change_set, with their status history and audit rows written after each batch. Placed rows flush right away, so the fit, overlap and hostname checks see the earlier rows in the same file. Duplicate serials within the file are caught in memory. **Unknown headers are now an error** (422 `unknown_columns {columns}`); they used to be a warning. 10k rows take about 7 s on SQLite. Possible future upsert matching (not built): `id` → `serial_number` → rack+host_name → EPIF external_id.

## Cabinet profiles (migrations p1_28_cabinet_profiles, p1_29_cabinet_profile_images)

A cabinet profile describes the cabinet alone, with doors and rails included. It is **profile creation only**: nothing references a cabinet profile yet (cabinets will link to profiles later). **Writes are admin only** (technician and read-only users get 403 `Requires role: admin`); every signed-in role can read. There is no password re-entry. Spec: `docs/db/MIGRATION_SPEC_CABINET_PROFILES.md`.

| Method + path | Notes |
|---|---|
| `GET /cabinet-profiles?status=&q=&limit=&offset=` | paginated (`limit` 1–500, default 50; `offset`; total in `X-Total-Count`), ordered by id; `q` searches manufacturer/model/name |
| `POST /cabinet-profiles` | create a **draft** (may be incomplete) → 201 |
| `GET /cabinet-profiles/{id}` | includes `readiness {ready, missing[]}`, `front_image`/`rear_image` refs |
| `PATCH /cabinet-profiles/{id}` | draft and published are editable; optional `expected_updated_at` |
| `DELETE /cabinet-profiles/{id}` | hard delete when unreferenced (any status); images cascade; audit snapshot → 204 |
| `POST /cabinet-profiles/{id}/publish` | draft → published (idempotent) |
| `POST /cabinet-profiles/{id}/retire` | published → retired (idempotent) |
| `POST /cabinet-profiles/{id}/unretire` | retired → **published** (never back to draft) |
| `POST /cabinet-profiles/{id}/clone {name?}` | new draft: version + 1, `supersedes_cabinet_profile_id` = source, all fields and **every image row** copied (new ids, same bytes/sha256) → 201. Without a name the server picks the first free of "<name> (copy)", "<name> (copy 2)", … (never 409); an explicit name that is taken → 409 `cabinet_profile_name_taken` |
| `PUT /cabinet-profiles/{id}/images/{front\|rear}` | raw body PNG/JPEG/WebP, ≤ 2 MiB, ≤ 4096 px; re-encoded without metadata; 512 px thumb + 1024 px `tex` WebP derived; `If-Match` → 412 `image_changed`; 201 created / 200 replaced |
| `DELETE /cabinet-profiles/{id}/images/{front\|rear}` | 204; 404 when there is none |
| `GET /cabinet-profiles/{id}/history` (admin, like `/audit-events`) | this profile's audit events newest first: `{id, occurred_at, action, actor_email, before, after}` (before/after = changed fields; create has only after, delete only before = full snapshot; actions `cabinet_profile.create|update|delete|publish|retire|unretire|clone|image.put|image.delete`; a publish/retire/unretire also has the listener's `update` with the status diff), paginated like lists; works after delete. **Every datetime** in an entry (`occurred_at` and any datetime inside `before`/`after`, including older audit rows stored without an offset, which are UTC) is ISO 8601 with `+00:00`, e.g. `2026-11-04T01:12:31.331192+00:00`. (Profile responses use pydantic's `Z` form; both are UTC.) |
| `GET /cabinet-profile-images/{id}/{face}?variant=original\|thumb\|tex&v=` | same caching as `/profile-images` (immutable with the current `?v=`, ETag/304, nosniff, sandbox CSP) |

**Fields.** `u_height` 1–100 (the form suggests 53). Outer `width_mm`, `height_mm`, `depth_mm`: only > 0, no upper caps (Preston), in the API and the DB. Values beyond the column range return 422 `invalid_dimension {fields[]}` on every database (checked in the API, after any inch conversion, on create and edit): any `*_mm` field above 2147483647, or `weight_capacity_kg` above 999,999.99. `usable_width_mm`/`usable_depth_mm` ≤ outer. `rack_unit_width` `19in | 23in`. `rail_type` `square_hole | round_hole | threaded` (the hole style). Fixed vs adjustable rails is not a field: fixed rails = `rail_depth_min_mm` equal to `rail_depth_max_mm`, adjustable = min < max. `rail_depth_min_mm` ≤ `rail_depth_max_mm` ≤ `depth_mm`. `front_door`/`rear_door` `none | perforated | solid | split`. `weight_capacity_kg` > 0, stored only, no warnings. `color_hex` `#RRGGBB`. `notes` ≤ 2000 chars. All lengths are stored and returned as whole **mm**.

**Units (also on device profiles).** `POST`/`PATCH` bodies of cabinet profiles and device profiles (`/device-types/{id}/profiles`) accept `"unit": "mm" | "in"` (default mm). It applies to every `*_mm` field in that body. Inches convert as mm = in × 25.4, rounded half-up to 1 mm for cabinet profiles and 0.1 mm for device profiles. Range checks run on the converted value. Responses never contain `unit`. Any other unit → 422 with error type `invalid_unit`.

**Response extras.** `rack_count` is always **0** until cabinets link to profiles. `created_by`, `published_by`, `retired_by` are stored (un-retire clears `retired_at`/`retired_by`). `updated_by` is the actor (email) of the latest audit event on the profile (edit, lifecycle or image change); there is no stored column. All timestamps (`created_at`, `updated_at`, `published_at`, `retired_at`, history `occurred_at`) carry a UTC offset (`+00:00`).

**Editing after publish.** Every field stays editable on a draft or published profile (admin only), as long as a published profile stays complete (422 `cabinet_profile_incomplete`). A retired profile is read-only (409 `cabinet_profile_retired`); un-retire or clone it. The fit lock (409 `cabinet_profile_in_use` on U height, outer size, rack-unit width, rail depths) comes when cabinets reference profiles.

**Publish rule.** manufacturer, model, name, `u_height`, outer width/height/depth and `rack_unit_width`. **Images are not required.** A published profile stays editable but can't be made incomplete. Lifecycle per spec §3: draft → published → retired → (un-retire) published; every other transition is 422 `invalid_status_transition`.

**Error codes** (`{"detail": {"code", "message", …}}` unless noted)
| Status | Code | When |
|---|---|---|
| 422 | `cabinet_profile_incomplete` `{missing[]}` | publish with fields missing, or a PATCH that would make a published profile incomplete |
| 422 | `invalid_status_transition` `{status, to}` | e.g. retire a draft, un-retire a published profile, publish a retired one |
| 422 | `invalid_dimension` `{fields[]}` | usable > outer, rail min > max, rail max > depth |
| 422 | request validation list, `type` = `invalid_unit` | unit not mm/in |
| 422 | request validation list | out-of-range or unknown enum value (e.g. `21in`, `glass`) |
| 409 | `cabinet_profile_name_taken` `{existing_id}` | manufacturer + model + name already used, ignoring case |
| 409 | `cabinet_profile_retired` | PATCH or image change on a retired profile |
| 409 | `cabinet_profile_in_use` `{reason: "superseded", superseded_by}` | DELETE while a newer version supersedes it (racks will also count later) |
| 409 | `version_conflict` `{current_updated_at, updated_by}` | PATCH with a stale `expected_updated_at` |
| 404 | plain | unknown id / image |
| 403 | plain `Requires role: admin` | any write by a technician or read-only user |
| 413/415/422/429/503 | `image_*` | the same image errors as device-profile images |

**Audit.** Every action is in `audit_events` with `entity_type=cabinet_profile`, under a change set: `cabinet_profile.create|update|delete` (the listener; delete carries the full snapshot) and `cabinet_profile.publish|retire|unretire|clone|image.put|image.delete`.
