"""collapse device status to install/active/decom

Revision ID: 3a77fe56d220
Revises: dafea626e30f
Create Date: 2026-10-24 13:32:15.568286

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = '3a77fe56d220'
down_revision: Union[str, Sequence[str], None] = 'dafea626e30f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


UP = {
    "planned": "install", "staged": "install",
    "active": "active", "maintenance": "active", "offline": "active", "failed": "active",
    "decommissioned": "decom",
}
DOWN = {"install": "planned", "active": "active", "decom": "decommissioned"}


def _remap(mapping: dict[str, str], fallback: str) -> None:
    cases = " ".join(f"WHEN '{old}' THEN '{new}'" for old, new in mapping.items())
    # unknown legacy strings fall back so every row ends up valid
    op.execute(f"UPDATE devices SET status = CASE status {cases} ELSE '{fallback}' END")


def upgrade() -> None:
    """Map old status values onto install/active/decom."""
    _remap(UP, "active")


def downgrade() -> None:
    """Map install/active/decom back to the old values."""
    _remap(DOWN, "active")
