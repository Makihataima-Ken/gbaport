"""The lifter's tests run twice: recompiled, and in the runtime's interpreter."""

import liftkit
import pytest

TWICE = {"test_armv4_quirks", "test_control_flow", "test_dataproc", "test_memory_system"}


def pytest_generate_tests(metafunc):
    if metafunc.module.__name__ in TWICE and "runner" in metafunc.fixturenames:
        metafunc.parametrize("runner", ["recompiled", "interpreted"], indirect=True)


@pytest.fixture(autouse=True)
def runner(request, monkeypatch):
    mode = getattr(request, "param", "recompiled")
    if mode == "interpreted" and request.node.get_closest_marker("recompiled_only"):
        pytest.skip("only recompiled code has missing code")
    monkeypatch.setattr(liftkit, "MODE", mode)
    return mode
