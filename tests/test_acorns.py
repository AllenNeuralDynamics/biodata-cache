"""Unit tests for acorn registry mechanism."""

from zombie_squirrel.acorns import ACORN_REGISTRY, NAMES


def test_acorn_registry_contains_all_functions():
    assert NAMES["upn"] in ACORN_REGISTRY
    assert NAMES["usi"] in ACORN_REGISTRY
    assert NAMES["ugt"] in ACORN_REGISTRY
    assert NAMES["basics"] in ACORN_REGISTRY
    assert NAMES["d2r"] in ACORN_REGISTRY
    assert NAMES["qc"] in ACORN_REGISTRY


def test_registry_values_are_callable():
    for name, func in ACORN_REGISTRY.items():
        assert callable(func), f"{name} is not callable"


def test_names_dict_completeness():
    for key in ["upn", "usi", "ugt", "basics", "d2r", "r2d", "qc"]:
        assert key in NAMES
