from __future__ import annotations

import socket
import threading

import pytest


def test_tcp_vs_udp_basic_roundtrip() -> None:
    # TCP: connection-oriented
    tcp_listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        tcp_listener.bind(("127.0.0.1", 0))
        tcp_listener.listen(1)
        tcp_host, tcp_port = tcp_listener.getsockname()

        tcp_received: list[bytes] = []

        def tcp_server() -> None:
            conn, _addr = tcp_listener.accept()
            with conn:
                tcp_received.append(conn.recv(1024))
                conn.sendall(b"pong")

        t = threading.Thread(target=tcp_server, daemon=True)
        t.start()

        with socket.create_connection((tcp_host, tcp_port), timeout=2) as tcp_client:
            tcp_client.sendall(b"ping")
            assert tcp_client.recv(1024) == b"pong"

        t.join(timeout=2)
        assert not t.is_alive()
        assert tcp_received == [b"ping"]
    finally:
        tcp_listener.close()

    # UDP: connectionless (datagrams)
    udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp_client = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        udp_sock.bind(("127.0.0.1", 0))
        udp_host, udp_port = udp_sock.getsockname()

        udp_received: list[bytes] = []

        def udp_server() -> None:
            data, _addr = udp_sock.recvfrom(2048)
            udp_received.append(data)

        u = threading.Thread(target=udp_server, daemon=True)
        u.start()

        udp_client.sendto(b"ping", (udp_host, udp_port))

        u.join(timeout=2)
        assert not u.is_alive()
        assert udp_received == [b"ping"]
    finally:
        udp_sock.close()
        udp_client.close()

def test_udp_send_to_unused_port_does_not_guarantee_error() -> None:
    # Demonstrates that UDP has no handshake: sending to a port with no listener
    # may not fail immediately (depends on ICMP behavior).
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.settimeout(0.2)
        sock.sendto(b"hello", ("127.0.0.1", 65500))

        # No response expected.
        # On Windows, a recvfrom() after sending to an unused port can raise
        # ConnectionResetError due to an ICMP Port Unreachable.
        with pytest.raises((TimeoutError, ConnectionResetError)):
            sock.recvfrom(1024)
    finally:
        sock.close()
