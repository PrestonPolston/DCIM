from enum import StrEnum
from typing import Literal


# Single source for allowed values (Pydantic schemas and DB CHECK constraints)
class DeviceStatus(StrEnum):
    install = "install"
    active = "active"
    decom = "decom"


class CableType(StrEnum):  # one shared list: adding a type = enum + CHECK-swap migration
    RJ45 = "RJ45"
    LC = "LC"
    DAC = "DAC"


class AssetType(StrEnum):  # item: fixed list; NULL = unknown
    server = "server"
    switch = "switch"
    patch_panel = "patch_panel"
    pdu = "pdu"
    router = "router"
    firewall = "firewall"
    storage = "storage"
    blank = "blank"
    shelf = "shelf"
    cable_manager = "cable_manager"  # p1_20 (approved 2026-10-24)
    other = "other"


AssetTypeLiteral = Literal["server", "switch", "patch_panel", "pdu", "router", "firewall", "storage", "blank",
                           "shelf", "cable_manager", "other"]


class ProfileStatus(StrEnum):
    draft = "draft"
    published = "published"
    retired = "retired"


class Mounting(StrEnum):
    rack_19in = "rack_19in"
    rack_23in = "rack_23in"
    shelf = "shelf"
    zero_u = "zero_u"
    other = "other"


ProfileStatusLiteral = Literal["draft", "published", "retired"]
MountingLiteral = Literal["rack_19in", "rack_23in", "shelf", "zero_u", "other"]


class Face(StrEnum):
    front = "front"
    rear = "rear"


class Orientation(StrEnum):
    N = "N"
    E = "E"
    S = "S"
    W = "W"


class Confidence(StrEnum):
    high = "high"
    medium = "medium"
    low = "low"
    unknown = "unknown"


class ProfileOrientation(StrEnum):  # D58: which side the ports face (switch variants); not Orientation (N/E/S/W)
    port_front = "port_front"
    power_front = "power_front"


class Airflow(StrEnum):
    front_to_rear = "front_to_rear"
    rear_to_front = "rear_to_front"
    side = "side"
    passive = "passive"


class PowerType(StrEnum):
    AC = "AC"
    DC = "DC"
    AC_DC = "AC_DC"


class RefKind(StrEnum):
    CHG = "CHG"
    DCREQ = "DCREQ"
    INC = "INC"
    OTHER = "OTHER"


class ContactRole(StrEnum):
    dc = "dc"
    vendor = "vendor"
    other = "other"


def sql_in(column: str, enum: type[StrEnum]) -> str:
    values = ",".join(f"'{v.value}'" for v in enum)
    return f"{column} IN ({values})"


# Literal types for Pydantic (plain strings in/out, same values as the enums)
DeviceStatusLiteral = Literal[tuple(v.value for v in DeviceStatus)]  # type: ignore[valid-type]
FaceLiteral = Literal[tuple(v.value for v in Face)]  # type: ignore[valid-type]
ConfidenceLiteral = Literal[tuple(v.value for v in Confidence)]  # type: ignore[valid-type]
AirflowLiteral = Literal[tuple(v.value for v in Airflow)]  # type: ignore[valid-type]
ProfileOrientationLiteral = Literal[tuple(v.value for v in ProfileOrientation)]  # type: ignore[valid-type]
PowerTypeLiteral = Literal[tuple(v.value for v in PowerType)]  # type: ignore[valid-type]
RefKindLiteral = Literal[tuple(v.value for v in RefKind)]  # type: ignore[valid-type]
ContactRoleLiteral = Literal[tuple(v.value for v in ContactRole)]  # type: ignore[valid-type]
OrientationLiteral = Literal[tuple(v.value for v in Orientation)]  # type: ignore[valid-type]


class Role(StrEnum):
    admin = "admin"
    technician = "technician"
    read_only = "read-only"


RoleLiteral = Literal[tuple(v.value for v in Role)]  # type: ignore[valid-type]

CableTypeLiteral = Literal[tuple(v.value for v in CableType)]  # type: ignore[valid-type]
