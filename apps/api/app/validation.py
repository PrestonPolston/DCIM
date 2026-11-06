import re
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, model_validator
from pydantic_core import PydanticCustomError

# Cells starting with these are spreadsheet formulas (OWASP CSV injection)
FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def formula_problem(value: str) -> bool:
    return value.startswith(FORMULA_START)


def neutralize_cell(value):
    """CSV export: prefix a quote so spreadsheets show formula-like text as text (OWASP)."""
    if isinstance(value, str) and value.startswith(FORMULA_START):
        return "'" + value
    return value


# D10 / R-3: credentials are never accepted or stored. Field/column names matching this are refused.
# N-5: names are normalised first (camelCase split, lower-case, any run of spaces / hyphens /
# punctuation -> "_"), so "iLO password", "ILO PW", "ilo-pw", "BMC Password" all match.
SECRET_TOKENS = {"password", "passwd", "passwrd", "pwd", "pw", "pass", "passphrase", "secret", "token",
                 "community", "apikey", "privatekey", "credential", "credentials"}
SECRET_PAIRS = {("api", "key"), ("private", "key"), ("access", "key"), ("secret", "key")}
SECRET_SUBSTRINGS = ("password", "passwd", "apikey", "privatekey")  # not "secret": secretary


def normalise_name(name: str) -> str:
    name = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", str(name).strip())
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def is_secret_name(name: str) -> bool:
    norm = normalise_name(name)
    tokens = norm.split("_")
    if any(t in SECRET_TOKENS for t in tokens):
        return True
    if any(pair in SECRET_PAIRS for pair in zip(tokens, tokens[1:])):
        return True
    return any(s in norm.replace("_", "") for s in SECRET_SUBSTRINGS)


def secret_keys(data: dict, declared) -> list[str]:
    return sorted(k for k in data if isinstance(k, str) and k not in declared and is_secret_name(k))


# D12 location aliases: Building = Site, Room = Hall (accepted in requests; responses are canonical)
LOCATION_ALIASES = {"site_id": "building_id", "site": "building", "hall_id": "room_id", "hall": "room"}


def merge_aliases(data: dict, fields) -> dict:
    """Move building/room keys onto site/hall; 422 if both are given and differ."""
    data = dict(data)
    for canonical, alias in LOCATION_ALIASES.items():
        if canonical not in fields or alias not in data:
            continue
        value = data.pop(alias)
        if canonical in data and data[canonical] != value:
            raise ValueError(f"{canonical} and {alias} are the same field and were given different values")
        data[canonical] = value
    return data


# Request bodies: unknown fields -> 422, strings trimmed, no formula/control characters
class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    check_input: ClassVar[bool] = True

    @model_validator(mode="before")
    @classmethod
    def _location_aliases(cls, data):
        if not isinstance(data, dict):
            return data
        if cls.check_input:
            found = secret_keys(data, cls.model_fields)
            if found:  # names only; the values are never echoed, logged or stored
                raise PydanticCustomError(
                    "secret_field_not_accepted",
                    "Credentials are not stored in DCIM; remove field(s): {fields}",
                    {"fields": ", ".join(found)},
                )
        return merge_aliases(data, cls.model_fields)

    @model_validator(mode="after")
    def _safe_strings(self):
        if not type(self).check_input:
            return self
        problems = []
        for name, value in self:
            if not isinstance(value, str):
                continue
            if formula_problem(value):
                problems.append(f"{name} must not start with = + - @ (spreadsheet formula)")
            elif any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
                problems.append(f"{name} must not contain control characters")
        if problems:
            raise ValueError("; ".join(problems))
        return self


# Response models built from DB rows: no input checks, extra attributes ignored
class OutputModel(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=False)
    check_input: ClassVar[bool] = False
