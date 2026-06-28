"""Rename extracted_content to page_document (canonical PageDocument column)

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-27 17:52:00.000000

Rationale:
    The column previously named `extracted_content` is the canonical, structured
    representation of a crawled page and the source of truth for all downstream AI
    services (embedding generation, categorization, search, analytics).

    Naming it `page_document` makes its purpose explicit and aligns with the
    storage tier contract:
        - PostgreSQL JSONB (page_document) -> structured metadata source of truth
        - Vector DB                        -> embeddings
        - Redis                            -> hot-cache + job queues (transient only)
        - S3 / object storage              -> raw HTML snapshots, screenshots, PDFs

    `extracted_content` is retained as a deprecated column (nullable) during the
    transition window so no running workers crash mid-crawl. It can be dropped
    in migration 0004 once all workers are redeployed.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '0003'
down_revision: Union[str, None] = '0002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add the canonical page_document column
    op.add_column('pages',
        sa.Column(
            'page_document',
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment=(
                "Canonical structured PageDocument. Source of truth for embedding, "
                "categorization, search and analytics. Never use Redis or S3 for this payload."
            )
        )
    )
    # Backfill page_document from extracted_content for rows already in DB
    op.execute("""
        UPDATE pages
        SET page_document = extracted_content
        WHERE extracted_content IS NOT NULL
          AND page_document IS NULL
    """)


def downgrade() -> None:
    op.drop_column('pages', 'page_document')
