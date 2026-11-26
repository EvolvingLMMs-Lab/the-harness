"""harness mcp serve: The Harness as an MCP server (package.toml [provides] commands).

    harness mcp serve                       on stdin and stdout (what an MCP client starts)
    harness mcp serve --http [--port 8790]  streamable HTTP at http://127.0.0.1:PORT/mcp

harness mcp alone, and harness mcp --http, are the same (what client configurations written
before the word serve name). The MCP servers the agent itself uses are managed by the core's
harness mcp list | add | remove | test."""

import argparse
import io
import sys

from .server import McpServer, http_server, serve_stdio


def main(arguments) -> int:
    arguments = list(arguments)
    if arguments[:1] == ["serve"]:
        arguments.pop(0)
    parser = argparse.ArgumentParser(prog="harness mcp serve",
                                     description="The Harness as an MCP server, for apps, editors and agents that "
                                                 "are MCP clients: on stdin and stdout, or with --http on "
                                                 "127.0.0.1. (harness mcp list | add | remove | test manage the "
                                                 "MCP servers the agent uses.)")
    parser.add_argument("--http", action="store_true", help="serve streamable HTTP at http://127.0.0.1:PORT/mcp")
    parser.add_argument("--port", type=int, default=None, help="the HTTP port (default 8790; 0: any free port)")
    args = parser.parse_args(list(arguments))
    if args.port is not None and not args.http:
        parser.error("--port goes with --http")
    server = McpServer()
    if args.http:
        httpd = http_server(server, 8790 if args.port is None else args.port)
        print(f"harness mcp: serving http://127.0.0.1:{httpd.server_address[1]}/mcp", file=sys.stderr, flush=True)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            httpd.server_close()
        return 0
    # stdout carries the protocol only: whatever else prints goes to stderr.
    stdin = io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8", errors="replace")
    stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", newline="\n", write_through=True)
    sys.stdout = sys.stderr
    try:
        serve_stdio(server, stdin, stdout)
    except KeyboardInterrupt:
        pass
    return 0
