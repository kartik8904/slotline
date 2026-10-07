from tests.integration.conftest import run_alembic


def test_upgrade_downgrade_upgrade_round_trip() -> None:
    for args in (("upgrade", "head"), ("downgrade", "base"), ("upgrade", "head")):
        result = run_alembic(*args)
        assert result.returncode == 0, result.stderr


def test_models_and_migrations_have_no_drift() -> None:
    result = run_alembic("check")
    assert result.returncode == 0, result.stderr + result.stdout
