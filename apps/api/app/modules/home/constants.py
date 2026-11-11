"""Named thresholds and list caps for GET /home/summary."""

# A draft is stale when it has been untouched for this many days or longer (inclusive).
STALE_DRAFT_DAYS = 14
# Retired profiles count as "recent" within this many days (inclusive).
RECENTLY_RETIRED_DAYS = 30
# Capped profile-health lists (needs review, stale drafts, recently retired, recently changed).
HOME_LIST_LIMIT = 5
# Unpositioned install/active devices on the Device issues tile.
UNPOSITIONED_DEVICE_LIMIT = 10
