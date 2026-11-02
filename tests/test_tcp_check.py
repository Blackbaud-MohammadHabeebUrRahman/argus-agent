"""Tests for the generic TCP port-open check."""

from __future__ import annotations

import asyncio
import contextlib

from argus.models import CheckStatus
from argus.monitor.tcp_check import TcpCheck


async def _spawn_server(port: int = 0) -> tuple[asyncio.Server, int]:
    """Start a trivial loopback TCP server; returns the server and bound port."""

    async def _handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        writer.close()
        with contextlib.suppress(Exception):
            await writer.wait_closed()

    server = await asyncio.start_server(_handle, "127.0.0.1", port)
    bound_port = server.sockets[0].getsockname()[1]
    return server, bound_port


async def test_tcp_check_passes_when_port_is_open():
    server, port = await _spawn_server()
    try:
        check = TcpCheck(name="tcp", service="svc", host="127.0.0.1", port=port, timeout=2)
        result = await check.execute()
        assert result.status == CheckStatus.OK
        assert result.details["port"] == port
    finally:
        server.close()
        await server.wait_closed()


async def test_tcp_check_critical_on_connection_refused():
    # Port 1 is reserved; connecting to 127.0.0.1:1 is reliably refused.
    check = TcpCheck(name="tcp", service="svc", host="127.0.0.1", port=1, timeout=2)
    result = await check.execute()
    assert result.status == CheckStatus.CRITICAL


async def test_tcp_check_critical_on_timeout():
    """Non-routable TEST-NET-1 address makes the connect hang until timeout fires."""
    check = TcpCheck(name="tcp", service="svc", host="192.0.2.1", port=12345, timeout=1)
    result = await check.execute()
    # Either a timeout or a routing-error "refused" — both are non-OK and
    # legitimate failure modes of a TCP probe to an unreachable host.
    assert result.status == CheckStatus.CRITICAL
