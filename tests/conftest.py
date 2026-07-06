import pytest
from hypothesis import HealthCheck, settings

settings.register_profile(
    "morphix",
    max_examples=100,
    suppress_health_check=[HealthCheck.too_slow],
)
settings.load_profile("morphix")


@pytest.fixture
def tmp_path(tmp_path):
    """Override tmp_path to return a fully resolved path.

    On Windows CI runners, tempfile paths can use 8.3 short names
    (e.g. RUNNER~1) while Path.resolve() expands them (runneradmin).
    CompressConfig.__post_init__ resolves input_path, so test comparisons
    against tmp_path must also be resolved to avoid mismatches.
    """
    return tmp_path.resolve()


def resolve_path(path_str: str) -> str:
    """Resolve a path string to avoid Windows 8.3 short-name mismatches.

    Use this in hypothesis property tests that create tempfile.TemporaryDirectory()
    and compare paths against CompressConfig-derived values (which are always resolved).
    """
    from pathlib import Path

    return str(Path(path_str).resolve())
