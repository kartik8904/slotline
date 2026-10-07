import os

# Settings() needs a database URL at import/creation time; integration tests override it.
os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://slotline:slotline@localhost:5432/slotline_test"
)
