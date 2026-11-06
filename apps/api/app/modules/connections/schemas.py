from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.validation import InputModel, OutputModel

from app.enums import CableTypeLiteral as CableType  # noqa: E402
PortKind = Literal["ethernet", "fiber", "console", "mgmt", "power", "tap", "patch", "other"]


class PortCreate(InputModel):
    name: str = Field(min_length=1, max_length=64)
    slot: str | None = Field(None, min_length=1, max_length=64)
    kind: PortKind | None = None
    connector: str | None = Field(None, max_length=32)
    speed_mbps: int | None = Field(None, gt=0)
    transceiver_make: str | None = Field(None, max_length=64)
    transceiver_model: str | None = Field(None, max_length=64)
    face: Literal["front", "rear"] | None = None


class Port(OutputModel, PortCreate):
    model_config = OutputModel.model_config
    id: int
    device_id: int
    role: str
    connection_id: int | None = None  # the live connection on this port, if any


class CableFields(InputModel):
    cable_type: CableType | None = None
    cable_label: str | None = Field(None, min_length=1, max_length=64)
    cable_color: str | None = Field(None, max_length=32)
    cable_length_m: Decimal | None = Field(None, gt=0, max_digits=8, decimal_places=2)
    notes: str | None = Field(None, max_length=2000)


class ConnectionCreate(CableFields):
    a_device_id: int
    a_port_id: int | None = None
    a_port_name: str | None = Field(None, min_length=1, max_length=64)
    b_device_id: int
    b_port_id: int | None = None
    b_port_name: str | None = Field(None, min_length=1, max_length=64)

    @model_validator(mode="after")
    def _one_port_ref(self):
        for side in ("a", "b"):
            if (getattr(self, f"{side}_port_id") is None) == (getattr(self, f"{side}_port_name") is None):
                raise ValueError(f"Give exactly one of {side}_port_id or {side}_port_name")
        return self


class ConnectionUpdate(CableFields):
    pass


class Cable(BaseModel):
    id: int
    cable_type: str | None
    label: str | None
    color: str | None
    length_m: Decimal | None


class End(BaseModel):
    device_id: int
    host_name: str
    status: str
    rack_id: int | None
    cabinet: str | None
    hall_id: int | None
    hall: str | None
    row: str | None
    position_u: int | None
    face: str | None
    port_id: int
    port_name: str
    slot: str | None


class Connection(BaseModel):
    id: int
    a: End
    b: End
    cable: Cable | None
    derived_status: Literal["install", "active", "decom"]
    notes: str | None
    created_at: datetime | None


class PortRef(BaseModel):
    id: int
    name: str
    slot: str | None


class FarDevice(BaseModel):
    id: int
    host_name: str
    rack_id: int | None
    cabinet: str | None
    hall: str | None
    position_u: int | None
    face: str | None
    status: str


class DeviceConnection(BaseModel):
    connection_id: int
    local_port: PortRef
    far_device: FarDevice
    far_port: PortRef
    cable: Cable | None
    local_status: str
    far_status: str
    derived_status: Literal["install", "active", "decom"]
    notes: str | None
