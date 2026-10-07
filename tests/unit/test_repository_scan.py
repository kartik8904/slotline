"""Every repository method takes `org_id` first (CLAUDE.md, plan "Conventions").

The only exceptions are listed here with a reason. `credential_lookup.py` is skipped as a
module: it holds the pre-tenant lookups (plan C21), where the credential reveals the org.
"""

import importlib
import inspect
import pkgutil

import slotline.repositories as repositories
from slotline.repositories.organizations import OrganizationRepository

EXEMPT_MODULES = {"slotline.repositories.credential_lookup"}
EXEMPT_METHODS = {
    ("OrganizationRepository", "create"): "creates a tenant, so no org_id exists yet",
}


def repository_classes() -> list[type]:
    classes: list[type] = []
    for module_info in pkgutil.iter_modules(repositories.__path__, "slotline.repositories."):
        if module_info.name in EXEMPT_MODULES:
            continue
        module = importlib.import_module(module_info.name)
        classes.extend(
            cls
            for name, cls in inspect.getmembers(module, inspect.isclass)
            if name.endswith("Repository") and cls.__module__ == module.__name__
        )
    return classes


def test_the_scan_finds_the_repositories() -> None:
    names = {cls.__name__ for cls in repository_classes()}
    assert {"UserRepository", "ApiKeyRepository", "RefreshTokenRepository"} <= names


def test_every_repository_method_takes_org_id_first() -> None:
    offenders = []
    for cls in repository_classes():
        for name, method in inspect.getmembers(cls, inspect.isfunction):
            if name.startswith("_") or (cls.__name__, name) in EXEMPT_METHODS:
                continue
            params = list(inspect.signature(method).parameters)
            if params[:2] != ["self", "org_id"]:
                offenders.append(f"{cls.__name__}.{name}{tuple(params)}")
    assert not offenders, f"repository methods must take org_id first: {offenders}"


def test_organization_get_is_the_one_lookup_by_its_own_id() -> None:
    """`OrganizationRepository.get(org_id)` fetches the tenant row itself, so it qualifies."""
    params = list(inspect.signature(OrganizationRepository.get).parameters)
    assert params == ["self", "org_id"]
