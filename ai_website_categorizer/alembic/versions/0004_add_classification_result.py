"""Add classification_result JSONB and category_id FK to pages table

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-27 19:10:00.000000

Rationale:
    Classification output is a rich, evolving JSON structure (stage results,
    confidence, reasoning, audit trail). JSONB gives us:
    - Schema flexibility as the ClassificationResult evolves
    - Full JSON path querying: pages WHERE classification_result->>'final_category' = 'Gummies'
    - GIN indexing for fast filtering if needed later

    category_id FK is kept separate as a scalar for fast JOIN queries.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '0004'
down_revision: Union[str, None] = '0003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('pages',
        sa.Column(
            'classification_result',
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment="Full ClassificationResult from all 3 stages. Source of truth for categorization."
        )
    )
    op.add_column('pages',
        sa.Column('category_id', postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.create_foreign_key(
        'fk_pages_category_id',
        'pages', 'categories',
        ['category_id'], ['id'],
        ondelete='SET NULL'
    )


def downgrade() -> None:
    op.drop_constraint('fk_pages_category_id', 'pages', type_='foreignkey')
    op.drop_column('pages', 'category_id')
    op.drop_column('pages', 'classification_result')
