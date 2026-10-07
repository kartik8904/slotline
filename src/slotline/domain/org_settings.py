"""Per-organisation settings written at signup (hold minutes: plan rule 3, C11; reminders: C14)."""

from typing import Any


def default_org_settings() -> dict[str, Any]:
    return {"hold_minutes": 5, "waitlist_offer_minutes": 15, "reminder_offsets_hours": [24, 2]}
