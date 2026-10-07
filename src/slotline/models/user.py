import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from slotline.models.base import Base
from slotline.models.mixins import IdMixin, TimestampMixin


class User(IdMixin, TimestampMixin, Base):
    """A staff member who logs in. The email is unique across all organisations (plan C1)."""

    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("role IN ('owner', 'staff')", name="role_valid"),
        CheckConstraint("email = lower(email)", name="email_lowercase"),
        Index("ix_users_org_id_id", "org_id", "id"),
    )

    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    email: Mapped[str] = mapped_column(Text, unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(server_default=text("true"), nullable=False)
    failed_login_count: Mapped[int] = mapped_column(
        Integer, server_default=text("0"), nullable=False
    )
    # Start of the current 15-minute failure window (plan C20)
    failed_login_window_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
