"""add artifact object links

Revision ID: 4b9f62e54f2f
Revises: a36de425aa90
Create Date: 2026-07-13 12:45:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "4b9f62e54f2f"
down_revision = "a36de425aa90"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "artifact_object_links",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=True),
        sa.Column("document_id", sa.Integer(), nullable=True),
        sa.Column("upload_id", sa.Integer(), nullable=True),
        sa.Column("entity_type", sa.String(length=64), nullable=False),
        sa.Column("entity_key", sa.String(length=160), nullable=False),
        sa.Column("relationship_type", sa.String(length=64), nullable=False),
        sa.Column("parser_name", sa.String(length=120), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["upload_id"], ["uploads.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "document_id",
            "entity_type",
            "entity_key",
            "relationship_type",
            name="uq_artifact_object_link",
        ),
    )
    op.create_index(op.f("ix_artifact_object_links_created_at"), "artifact_object_links", ["created_at"], unique=False)
    op.create_index(op.f("ix_artifact_object_links_document_id"), "artifact_object_links", ["document_id"], unique=False)
    op.create_index(op.f("ix_artifact_object_links_entity_key"), "artifact_object_links", ["entity_key"], unique=False)
    op.create_index(op.f("ix_artifact_object_links_entity_type"), "artifact_object_links", ["entity_type"], unique=False)
    op.create_index(
        op.f("ix_artifact_object_links_parser_name"),
        "artifact_object_links",
        ["parser_name"],
        unique=False,
    )
    op.create_index(op.f("ix_artifact_object_links_project_id"), "artifact_object_links", ["project_id"], unique=False)
    op.create_index(
        op.f("ix_artifact_object_links_relationship_type"),
        "artifact_object_links",
        ["relationship_type"],
        unique=False,
    )
    op.create_index(op.f("ix_artifact_object_links_upload_id"), "artifact_object_links", ["upload_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_artifact_object_links_upload_id"), table_name="artifact_object_links")
    op.drop_index(op.f("ix_artifact_object_links_relationship_type"), table_name="artifact_object_links")
    op.drop_index(op.f("ix_artifact_object_links_project_id"), table_name="artifact_object_links")
    op.drop_index(op.f("ix_artifact_object_links_parser_name"), table_name="artifact_object_links")
    op.drop_index(op.f("ix_artifact_object_links_entity_type"), table_name="artifact_object_links")
    op.drop_index(op.f("ix_artifact_object_links_entity_key"), table_name="artifact_object_links")
    op.drop_index(op.f("ix_artifact_object_links_document_id"), table_name="artifact_object_links")
    op.drop_index(op.f("ix_artifact_object_links_created_at"), table_name="artifact_object_links")
    op.drop_table("artifact_object_links")
