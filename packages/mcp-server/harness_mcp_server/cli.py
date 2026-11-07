"""harness mcp: The Harness as an MCP server (package.toml [provides] commands).

    harness mcp                       on stdin and stdout (what a coding agent starts)
    harness mcp --http [--port 8790]  streamable HTTP at http://127.0.0.1:PORT/mcp
"""

import argparse
import io
import sys

from .server import McpServer, http_server, serve_stdio


def main(arguments) -> int:
    parser = argparse.ArgumentParser(prog="harness mcp",
                                     description="The Harness as an MCP server, for Claude Code, Codex, Cursor "
                                                 "and other MCP clients: on stdin and stdout, or with --http "
                                                 "on 127.0.0.1")
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
