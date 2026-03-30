from __future__ import annotations

import asyncio
import subprocess
from dataclasses import dataclass

_DEBUGPY_PORTS = range(5678, 5686)
_PROBE_TIMEOUT = 0.2


@dataclass(frozen=True, slots=True)
class DiscoveredServer:
    host: str
    port: int
    pid: int | None
    process_name: str
    alive: bool


async def probe_server(host: str, port: int, *, timeout: float = _PROBE_TIMEOUT) -> bool:
    try:
        _reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=timeout
        )
        writer.close()
        await writer.wait_closed()
    except (OSError, TimeoutError):
        return False
    return True


async def discover_debugpy_servers(
    host: str = "127.0.0.1",
    ports: range | None = None,
) -> list[DiscoveredServer]:
    if ports is None:
        ports = _DEBUGPY_PORTS

    probes = [probe_server(host, port) for port in ports]
    results = await asyncio.gather(*probes)

    servers: list[DiscoveredServer] = []
    for port, alive in zip(ports, results, strict=True):
        if alive:
            pid, name = await _resolve_pid(host, port)
            servers.append(
                DiscoveredServer(host=host, port=port, pid=pid, process_name=name, alive=True)
            )
    return servers


async def probe_history_entries(
    entries: list[tuple[str, int]],
) -> dict[tuple[str, int], bool]:
    probes = [probe_server(host, port) for host, port in entries]
    results = await asyncio.gather(*probes)
    return {entry: alive for entry, alive in zip(entries, results, strict=True)}


async def _resolve_pid(host: str, port: int) -> tuple[int | None, str]:
    if host not in ("127.0.0.1", "localhost", "0.0.0.0", "::1"):
        return None, "remote"
    try:
        result = await asyncio.to_thread(
            subprocess.run,
            ["lsof", "-i", f"TCP:{port}", "-sTCP:LISTEN", "-t"],
            capture_output=True,
            text=True,
            check=False,
            timeout=1.0,
        )
        if result.returncode == 0 and result.stdout.strip():
            pid = int(result.stdout.strip().splitlines()[0])
            name = await _resolve_process_name(pid)
            return pid, name
    except (subprocess.TimeoutExpired, ValueError, OSError):
        pass
    return None, "unknown"


async def _resolve_process_name(pid: int) -> str:
    try:
        result = await asyncio.to_thread(
            subprocess.run,
            ["ps", "-p", str(pid), "-o", "args="],
            capture_output=True,
            text=True,
            check=False,
            timeout=1.0,
        )
        if result.returncode == 0 and result.stdout.strip():
            args = result.stdout.strip()
            # Extract the script name from python command line
            parts = args.split()
            for part in reversed(parts):
                if part.endswith(".py"):
                    return part.rsplit("/", 1)[-1]
            return parts[-1].rsplit("/", 1)[-1] if parts else "unknown"
    except (subprocess.TimeoutExpired, ValueError, OSError):
        pass
    return "unknown"
