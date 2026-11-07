"""harness acp: The Harness as an Agent Client Protocol agent on stdio (package.toml
[provides] commands). An editor starts it and talks to it; it is not run by hand."""

import argparse
import io
import os
import sys

from .agent import Agent


def main(arguments=None) -> int:
    parser = argparse.ArgumentParser(prog="harness acp",
                                     description="The agent on this computer for an editor that speaks the Agent "
                                                 "Client Protocol (Zed and others): JSON-RPC on stdin and stdout, "
                                                 "logs on stderr.")
    parser.add_argument("--workspace", default="auto",
                        help="where a session's tasks run, as harness run --workspace takes it (default auto: "
                             "the session host picks)")
    args = parser.parse_args(list(arguments or []))
    # The protocol gets the process's stdout to itself: anything else written there
    # (by this process or one it starts) goes to stderr.
    sys.stdout.flush()
    writer = io.TextIOWrapper(os.fdopen(os.dup(1), "wb"), encoding="utf-8", newline="\n", write_through=True)
    os.dup2(2, 1)
    reader = io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8")
    try:
        return Agent(workspace=args.workspace).serve(reader, writer)
    except KeyboardInterrupt:
        return 130
    finally:
        try:
            writer.close()
        except OSError:
            pass
