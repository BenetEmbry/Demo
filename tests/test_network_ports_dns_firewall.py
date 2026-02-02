from __future__ import annotations

import errno
import socket
import threading
import time

import pytest


def test_dns_resolution_localhost() -> None:
    infos = socket.getaddrinfo("localhost", 80, type=socket.SOCK_STREAM)
    assert infos

    addrs = {info[4][0] for info in infos}
    # Windows often returns both IPv4 and IPv6.
    assert "127.0.0.1" in addrs or "::1" in addrs


def test_ports_open_vs_closed_connection_refused() -> None:
    # Open: create a TCP listener.
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    host, port = listener.getsockname()

    def server() -> None:
        conn, _addr = listener.accept()
        with conn:
            conn.recv(1)

    t = threading.Thread(target=server, daemon=True)
    t.start()

    client = socket.create_connection((host, port), timeout=2)
    with client:
        client.sendall(b"x")

    listener.close()

    # Closed: pick another ephemeral port that we are not listening on.
    closed_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    closed_sock.bind(("127.0.0.1", 0))
    closed_host, closed_port = closed_sock.getsockname()
    closed_sock.close()

    # Depending on local firewall / OS behavior, a connection attempt to a port
    # with no listener may be refused immediately OR may time out.
    try:
        socket.create_connection((closed_host, closed_port), timeout=0.5)
        pytest.fail("Expected connection failure (refused or timeout)")
    except TimeoutError:
        # Silent drop / no response.
        pass
    except OSError as e:
        # Active reject: Windows WSAECONNREFUSED (10061), POSIX ECONNREFUSED.
        assert e.errno in (errno.ECONNREFUSED, 10061)


def test_firewall_like_behavior_timeout_vs_refused() -> None:
    # "Refused" resembles an active reject (port closed)
    closed_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    closed_sock.bind(("127.0.0.1", 0))
    host, port = closed_sock.getsockname()
    closed_sock.close()

    with pytest.raises(OSError):
        socket.create_connection((host, port), timeout=0.2)

    # "Timeout" resembles silent drop / no response.
    # We simulate that by accepting and then not responding.
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    host2, port2 = listener.getsockname()

    def slow_server() -> None:
        conn, _addr = listener.accept()
        with conn:
            time.sleep(1.0)

    t = threading.Thread(target=slow_server, daemon=True)
    t.start()

    client = socket.create_connection((host2, port2), timeout=0.5)
    client.settimeout(0.2)
    with client:
        with pytest.raises(TimeoutError):
            client.recv(1)

    listener.close()
