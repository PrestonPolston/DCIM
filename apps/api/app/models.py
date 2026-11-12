# Import every table model so SQLModel.metadata (and Alembic) sees them all
from app.modules.device_types.models import DeviceTypeProfileRow, DeviceTypeRow  # noqa: F401
from app.modules.devices.models import DeviceRow  # noqa: F401
from app.modules.locations.models import HallRow, RackRow, RackRowRow, SiteRow  # noqa: F401
from app.modules.history.models import (  # noqa: F401
    ChangeSetRow, RestoredDeviceRow,
    DevicePlacementHistoryRow,
    DeviceNameHistoryRow,
    DeviceStatusHistoryRow,
)
from app.modules.directory.models import (  # noqa: F401
    ContactRow, GroupRow, ProjectContactRow, ProjectReferenceRow, ProjectRow, VendorRow,
)
from app.modules.audit.models import AuditEventRow  # noqa: F401
from app.modules.auth.models import SessionRow, UserRow  # noqa: F401
from app.modules.connections.models import CableRow, ConnectionRow, DevicePortRow  # noqa: F401,E402
from app.modules.images.models import ProfileImageRow  # noqa: F401,E402
from app.modules.devices.slots import DeviceRuSlotRow  # noqa: F401,E402  (P1-10; also registers the slot sync hook)
from app.modules.cabinet_profiles.models import CabinetProfileImageRow, CabinetProfileRow  # noqa: F401,E402
from app.modules.jobs.models import EpifPsuRow, EpifRequestRow, ImportRowRow, JobImportRow, JobOpenItemRow  # noqa: F401,E402
