"""single unique device serial_number

Revision ID: dafea626e30f
Revises: a881da8cd921
Create Date: 2026-10-24 13:28:26.058186

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'dafea626e30f'
down_revision: Union[str, Sequence[str], None] = 'a881da8cd921'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Merge serial/asset_tag into one unique serial_number."""
    with op.batch_alter_table('devices', schema=None) as batch_op:
        batch_op.add_column(sa.Column('serial_number', sqlmodel.sql.sqltypes.AutoString(), nullable=True))
    op.execute("UPDATE devices SET serial_number = COALESCE(NULLIF(serial, ''), NULLIF(asset_tag, ''))")
    with op.batch_alter_table('devices', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_devices_asset_tag'))
        batch_op.drop_index(batch_op.f('ix_devices_serial'))
        batch_op.create_unique_constraint('uq_devices_serial_number', ['serial_number'])
        batch_op.drop_column('asset_tag')
        batch_op.drop_column('serial')


def downgrade() -> None:
    """Restore serial/asset_tag (serial_number goes back into serial)."""
    with op.batch_alter_table('devices', schema=None) as batch_op:
        batch_op.add_column(sa.Column('serial', sa.VARCHAR(), nullable=True))
        batch_op.add_column(sa.Column('asset_tag', sa.VARCHAR(), nullable=True))
    op.execute("UPDATE devices SET serial = serial_number")
    with op.batch_alter_table('devices', schema=None) as batch_op:
        batch_op.drop_constraint('uq_devices_serial_number', type_='unique')
        batch_op.create_index(batch_op.f('ix_devices_serial'), ['serial'], unique=False)
        batch_op.create_index(batch_op.f('ix_devices_asset_tag'), ['asset_tag'], unique=False)
        batch_op.drop_column('serial_number')
