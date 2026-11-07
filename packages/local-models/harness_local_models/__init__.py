"""The local-models package's library: where self-hosted models run. deploy.py (a deploy
file, the harness's own placement), supervisor.py (start, stop, status), broker.py (the
server that starts on-demand services and swaps them on a GPU), provision.py (services'
environments and weights), tools.py (GPUs, the deploy's doctor, fetch), commands.py
(harness services, up, down, status, fetch) and host.py (the deploy the core resolves
agents against)."""
