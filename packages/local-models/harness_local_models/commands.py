"""The package's commands (package.toml [provides] commands):

    harness services [--json]                  the service manifests
    harness up | down | status [NAMES] [--deploy D] [--json]
                                               start, stop or show a deploy's services
    harness fetch NAMES [--deploy D]           download services' weights into the deploy's
"""

import argparse
import json
import sys


def _output(value):
    print(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False))


def _table(rows, columns) -> str:
    cells = [[("" if row.get(column) is None else str(row.get(column))) for column in columns] for row in rows]
    widths = [max([len(column)] + [len(line[i]) for line in cells]) for i, column in enumerate(columns)]
    lines = ["  ".join(column.ljust(width) for column, width in zip(columns, widths))]
    lines += ["  ".join(cell.ljust(width) for cell, width in zip(line, widths)) for line in cells]
    return "\n".join(lines)


def _log(message):
    print(message, file=sys.stderr, flush=True)


def services(argv) -> int:
    parser = argparse.ArgumentParser(prog="harness services", description="List the services (services/*.toml)")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    from harness.sdk import load_services

    rows = [{"service": spec.name, "kind": spec.kind, "protocol": spec.protocol, "port": spec.port,
             "vram_gb": spec.vram_gb, "summary": spec.summary} for spec in load_services().values()]
    _output(rows) if args.json else print(_table(rows, ["service", "kind", "protocol", "port", "vram_gb", "summary"]))
    return 0


def _deploy_command(name: str, text: str, argv):
    parser = argparse.ArgumentParser(prog=f"harness {name}", description=text)
    parser.add_argument("names", nargs="*", help="services (default: all the deploy runs)")
    parser.add_argument("--deploy", help="deploy name (configs/deploy/<name>.toml) or path; default $HARNESS_DEPLOY")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    from harness_local_models import supervisor
    from harness_local_models.deploy import automatic, load_deploy

    deploy = load_deploy(args.deploy)
    if deploy.automatic:
        # No deploy file: the harness's own placement, of the services named or of the
        # default agent's.
        from harness.sdk import resolve_agent

        if args.names:
            deploy = automatic([item for item in args.names if item in deploy.services], log=_log)
        else:
            deploy = resolve_agent().deploy
    if name == "down":
        supervisor.down(deploy, args.names or None, log=_log)
        return 0
    rows = supervisor.up(deploy, args.names or None, log=_log) if name == "up" else \
        supervisor.status(deploy, args.names or None)
    _output(rows) if args.json else print(_table(rows, ["service", "kind", "mode", "gpu", "url", "up", "pid"]))
    return 0 if all(row.get("up") is not False for row in rows) else 1


def up(argv) -> int:
    return _deploy_command("up", "Start the resident services of a deploy (all, or the ones named)", argv)


def down(argv) -> int:
    return _deploy_command("down", "Stop services that harness up started", argv)


def status(argv) -> int:
    return _deploy_command("status", "Where each service of a deploy runs and whether it answers", argv)


def fetch(argv) -> int:
    parser = argparse.ArgumentParser(prog="harness fetch", description="Download the weights of services into "
                                                                       "the deploy's weights root")
    parser.add_argument("names", nargs="+")
    parser.add_argument("--deploy", help="deploy name (configs/deploy/<name>.toml) or path; default $HARNESS_DEPLOY")
    args = parser.parse_args(argv)
    from harness_local_models import tools
    from harness_local_models.deploy import load_deploy

    deploy = load_deploy(args.deploy)
    return 1 if sum(tools.fetch(deploy, name, log=_log) for name in args.names) else 0
