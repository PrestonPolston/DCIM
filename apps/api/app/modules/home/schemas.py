"""Response models for GET /home/summary and GET /home/search."""
from typing import Literal

from pydantic import BaseModel, Field, model_serializer


class ParkedTile(BaseModel):
    key: str
    status: Literal["not_available"] = "not_available"
    message: str


class NeedsReviewItem(BaseModel):
    id: int
    name: str
    usable_issue: str | None
    usable_issues: list[str]


class StaleDraftItem(BaseModel):
    id: int
    name: str
    updated_at: str


class RecentlyRetiredItem(BaseModel):
    id: int
    name: str
    retired_at: str


class RecentlyChangedItem(BaseModel):
    id: int
    name: str
    status: Literal["draft", "published", "retired"]
    updated_at: str
    published_at: str | None
    retired_at: str | None


class UnpositionedDeviceItem(BaseModel):
    id: int
    hostname: str
    status: str
    updated_at: str


class NeedsReviewList(BaseModel):
    count: int
    truncated: bool
    items: list[NeedsReviewItem]
    by_issue: dict[str, int]
    filter: str = "status=published&usable=false"


class StaleDraftsList(BaseModel):
    count: int
    truncated: bool
    items: list[StaleDraftItem]
    filter: str = "status=draft"


class RecentlyRetiredList(BaseModel):
    count: int
    truncated: bool
    items: list[RecentlyRetiredItem]
    filter: str = "status=retired"


class RecentlyChangedList(BaseModel):
    count: int
    truncated: bool
    items: list[RecentlyChangedItem]


class StatusCounts(BaseModel):
    draft: int = 0
    published: int = 0
    retired: int = 0


class ProfileHealthTile(BaseModel):
    key: Literal["profile_health"] = "profile_health"
    by_status: StatusCounts
    needs_review: NeedsReviewList
    stale_drafts: StaleDraftsList
    recently_retired: RecentlyRetiredList
    recently_changed: RecentlyChangedList


class UnpositionedList(BaseModel):
    count: int
    truncated: bool
    items: list[UnpositionedDeviceItem]
    filter: str = "status=install&status=active&unplaced=true"


class DeviceIssuesTile(BaseModel):
    key: Literal["device_issues"] = "device_issues"
    no_position: UnpositionedList
    needs_power_assignment: ParkedTile
    port_conflicts: ParkedTile
    open_power_mismatches: ParkedTile


class MyWork(BaseModel):
    jobs: ParkedTile
    dcreqs: ParkedTile
    held_imports: ParkedTile


class AdminSection(BaseModel):
    profile_health: ProfileHealthTile
    device_issues: DeviceIssuesTile
    workload: ParkedTile


class HomeSummary(BaseModel):
    generated_at: str = Field(description="UTC instant this payload was built, ISO 8601 with Z")
    my_work: MyWork
    admin: AdminSection | None = Field(default=None, description="Present for admins only; omitted for other roles")

    @model_serializer(mode="wrap")
    def _omit_empty_admin(self, handler):
        data = handler(self)
        if data.get("admin") is None:
            data.pop("admin", None)
        return data



class SearchDeviceItem(BaseModel):
    id: int
    label: str
    hostname: str
    serial: str | None
    status: str
    rack_id: int | None
    rack_name: str | None
    position_u: int | None


class SearchCabinetItem(BaseModel):
    id: int
    label: str
    name: str
    row_id: int
    row_name: str
    hall_id: int
    hall_name: str


class SearchRowItem(BaseModel):
    id: int
    label: str
    name: str
    hall_id: int
    hall_name: str
    site_id: int
    site_name: str


class SearchPlaceItem(BaseModel):
    """A hall hit, with the site it belongs to."""
    id: int
    label: str
    name: str
    site_id: int
    site_name: str


class DeviceSearchGroup(BaseModel):
    key: Literal["devices"] = "devices"
    count: int
    truncated: bool
    items: list[SearchDeviceItem]


class CabinetSearchGroup(BaseModel):
    key: Literal["cabinets"] = "cabinets"
    count: int
    truncated: bool
    items: list[SearchCabinetItem]


class RowSearchGroup(BaseModel):
    key: Literal["rows"] = "rows"
    count: int
    truncated: bool
    items: list[SearchRowItem]


class HallSearchGroup(BaseModel):
    key: Literal["halls"] = "halls"
    count: int
    truncated: bool
    items: list[SearchPlaceItem]


SearchGroup = DeviceSearchGroup | CabinetSearchGroup | RowSearchGroup | HallSearchGroup


class HomeSearch(BaseModel):
    query: str
    generated_at: str = Field(description="UTC instant this payload was built, ISO 8601 with Z")
    groups: list[SearchGroup]
    parked: list[ParkedTile]
