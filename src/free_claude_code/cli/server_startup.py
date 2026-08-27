"""Lightweight shared probes used before starting an FCC server owner."""

import socket


def server_port_is_occupied(host: str, port: int) -> bool:
    """Detect a listener before Uvicorn can emit a noisy bind traceback."""

    connect_host = host.strip() if host else "127.0.0.1"
    if connect_host in {"0.0.0.0", "::", "[::]"}:
        connect_host = "127.0.0.1"
    connect_host = connect_host.strip("[]")
    try:
        with socket.create_connection((connect_host, port), timeout=0.2):
            return True
    except OSError:
        return False
