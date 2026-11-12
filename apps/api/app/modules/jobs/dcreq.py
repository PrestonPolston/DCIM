"""DCREQ job number (D73): DCREQ000 + 4 digits, 12 characters. The service trims and uppercases first."""
import re

DCREQ_RE = re.compile(r"DCREQ000[0-9]{4}")
DCREQ_LEN = 12
_DIGITS = "('0','1','2','3','4','5','6','7','8','9')"


def dcreq_sql(col: str) -> str:
    """The format as portable SQL (identical on SQLite and Postgres; no GLOB or ~)."""
    digits = " AND ".join(f"substr({col}, {i}, 1) IN {_DIGITS}" for i in range(9, 13))
    return f"length({col}) = {DCREQ_LEN} AND substr({col}, 1, 8) = 'DCREQ000' AND {digits}"


def normalize_dcreq(value: str | None) -> str | None:
    """Trim + uppercase, then validate. Returns the canonical DCREQ, or None if the format is wrong."""
    if not isinstance(value, str):
        return None
    norm = value.strip().upper()
    return norm if DCREQ_RE.fullmatch(norm) else None
