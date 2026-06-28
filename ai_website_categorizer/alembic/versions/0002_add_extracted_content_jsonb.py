"""Add extracted_content JSONB and content_hash to pages

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-27 17:17:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '0002'
down_revision: Union[str, None] = '0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('pages',
        sa.Column('extracted_at', sa.DateTime(), nullable=True)
    )
    op.add_column('pages',
        sa.Column('extracted_content', postgresql.JSONB(astext_type=sa.Text()), nullable=True)
    )
    op.add_column('pages',
        sa.Column('content_hash', sa.String(length=64), nullable=True)
    )
    op.create_index(op.f('ix_pages_content_hash'), 'pages', ['content_hash'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_pages_content_hash'), table_name='pages')
    op.drop_column('pages', 'content_hash')
    op.drop_column('pages', 'extracted_content')
    op.drop_column('pages', 'extracted_at')
