"""On-demand services, as a client sees them: before each call to a service a deploy runs
on demand, ensure() asks the deploy's broker to make it answer (the local-models
package's broker starts it, swaps it on a shared GPU and stops it when idle). Clients ask
at most every CLIENT_INTERVAL seconds while a service is in use."""

import threading
import time

from ..core.http import post_json


CLIENT_INTERVAL = 2.0   # a client asks the broker at most this often per service


_LAST: dict[tuple, float] = {}
_GUARD = threading.Lock()


def ensure(config: dict | None, *, timeout: float = 1800.0) -> None:
    """Before calling a service: when its client config is on demand, ask the broker to
    make it answer (at most every CLIENT_INTERVAL seconds while it is in use)."""
    on_demand = (config or {}).get("on_demand") if isinstance(config, dict) else None
    if not on_demand:
        return
    key = (on_demand["url"], on_demand["service"])
    with _GUARD:
        if time.monotonic() - _LAST.get(key, -1e9) < CLIENT_INTERVAL:
            return
    try:
        post_json(on_demand["url"].rstrip("/") + "/ensure", {"service": on_demand["service"]}, timeout=timeout)
    except Exception as error:
        detail = getattr(error, "read", lambda: b"")().decode(errors="replace") if hasattr(error, "read") else ""
        raise RuntimeError(f"service {on_demand['service']} could not be started on demand: {error} {detail}") from error
    with _GUARD:
        _LAST[key] = time.monotonic()
