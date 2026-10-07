import re

MAX_SLUG_LENGTH = 40


def slugify(name: str) -> str:
    """Lowercase, ASCII letters and digits separated by single hyphens; never empty."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:MAX_SLUG_LENGTH].strip("-")
    return slug or "org"
