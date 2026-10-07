"""Fixtures for loading isolated record-consistency checks from temporary modules."""

import importlib.util
import sys
import textwrap

import pytest

import biodata_cache.registry as registry
from biodata_cache.backend import MemoryBackend
from biodata_cache.cache_table_helpers.record_consistency import framework


@pytest.fixture(autouse=True)
def reset_backend():
    registry.BACKEND = MemoryBackend()


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    """Swap in empty registries and return a loader for check modules written to ``tmp_path``."""
    monkeypatch.setattr(framework, "CHECKS", {})
    monkeypatch.setattr(framework, "SOURCES", {})
    monkeypatch.setattr(framework, "SOURCE_ROOT", tmp_path)

    def load_module(name, body):
        path = tmp_path / f"{name}.py"
        path.write_text(textwrap.dedent(body))
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, name, module)
        spec.loader.exec_module(module)
        return module

    return load_module
