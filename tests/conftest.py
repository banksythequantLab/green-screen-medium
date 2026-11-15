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
