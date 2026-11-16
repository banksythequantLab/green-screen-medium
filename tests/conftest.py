import os
import socket
import pytest

GS_HOST = os.environ.get("GS_HOST", "192.168.68.72")
GS_PORT = int(os.environ.get("GS_PORT", "3270"))


@pytest.fixture(scope="session")
def host_reachable():
    try:
        with socket.create_connection((GS_HOST, GS_PORT), timeout=5):
            pass
    except (OSError, socket.timeout):
        pytest.skip(f"TN3270 host {GS_HOST}:{GS_PORT} not reachable — skipping integration tests")


def finalize_fakes(fakes):
    """Terminate every fake, then re-raise the first stored script failure.

    All fakes are terminated before any failure is raised so nothing leaks.
    """
    for f in fakes:
        f.terminate()
        try:
            f.stdin.close()
        except Exception:
            pass
    for f in fakes:
        f.raise_if_failed()


@pytest.fixture
def fake_s3270_factory():
    """Opt-in factory creating FakeS3270 instances: ``fake = factory(script)``.

    At teardown each fake is terminated and ``raise_if_failed()`` is called,
    so a script mismatch or exhaustion on the handler thread fails the test
    instead of passing silently. Existing tests that build FakeS3270 directly
    are unaffected.
    """
    from greenscreen.connector.testing.fake import FakeS3270

    fakes = []

    def _make(script):
        f = FakeS3270(script)
        fakes.append(f)
        return f

    yield _make
    finalize_fakes(fakes)
