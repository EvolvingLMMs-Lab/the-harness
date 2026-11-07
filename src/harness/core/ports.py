"""Ports on this machine that a process may listen on now: the session host's, a suite's
workers', the computer's workspaces', a service's. No bench hard-codes one, so they never
take each other's (a worker on 8790 and the computer's own on 8790 once did). Standard
library only."""

import os
import socket


class OwnPort:
    """Place before a socketserver base to reject competing listeners on the same address.

    Windows needs an exclusive bind. POSIX can reuse ports after a restart without
    sharing a live listener. A plain Windows wildcard socket can still coexist with
    an exclusive socket bound to a specific address.
    """

    allow_reuse_address = os.name != "nt"
    allow_reuse_port = False

    def server_bind(self):
        if os.name == "nt":
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def free_port(preferred: int | None = None) -> int:
    """`preferred` when nothing listens on it on 127.0.0.1, else a port the system gives."""
    if preferred and _free(preferred):
        return preferred
    return free_ports(1)[0]


def free_ports(count: int, start: int | None = None) -> list[int]:
    """`count` distinct ports free now: from `start` upward, skipping the taken ones (a
    deploy that names its workers' ports), else ports the system gives."""
    if start is None:
        # Held open together, so the system gives distinct ones.
        probes = [socket.socket() for _ in range(count)]
        try:
            for probe in probes:
                probe.bind(("127.0.0.1", 0))
            return [probe.getsockname()[1] for probe in probes]
        finally:
            for probe in probes:
                probe.close()
    ports, port = [], int(start)
    while len(ports) < count:
        if port > 65535:
            raise RuntimeError(f"no {count} free ports from {start}")
        if _free(port):
            ports.append(port)
        port += 1
    return ports


def _free(port: int) -> bool:
    with socket.socket() as probe:
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True
