from typing import Any

from sqlalchemy import String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from slotline.models.base import Base
from slotline.models.mixins import IdMixin, TimestampMixin


class Organization(IdMixin, TimestampMixin, Base):
    """A tenant: one clinic or salon. Its `id` is the `org_id` carried by every other table."""

    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(String(100))
    slug: Mapped[str] = mapped_column(String(60), unique=True)
    timezone: Mapped[str] = mapped_column(Text)
    settings: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb"), nullable=False
    )
