import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from slotline.models.base import Base
from slotline.models.mixins import IdMixin, TimestampMixin


class ApiKey(IdMixin, TimestampMixin, Base):
    """A machine client (for example Vaani). Only the SHA-256 hash of the key is stored."""

    __tablename__ = "api_keys"
    __table_args__ = (Index("ix_api_keys_org_id_id", "org_id", "id"),)

    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    name: Mapped[str] = mapped_column(String(100))
    prefix: Mapped[str] = mapped_column(String(16))
    key_hash: Mapped[str] = mapped_column(Text, unique=True)
    scopes: Mapped[list[str]] = mapped_column(ARRAY(Text))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
