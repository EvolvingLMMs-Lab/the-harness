"""A headless Chrome that several browser workers share, each in a context of its own
(cookies, storage and pages apart): `python -m benches.browser.chrome` prints one line,
{"endpoint": "ws://127.0.0.1:PORT/<random path>"}, and runs until its standard input
closes (the harness that started it ends, or closes it).

It is Playwright's own browser server (launchServer of the Node driver that comes with
the Python package), so a worker attaches with chromium.connect(endpoint) and a context
it makes is a real browser context. The random path is the key: other users of this
machine cannot drive the browser through the port alone. Run in the browser bench's
environment; Chrome must already be installed (nothing is downloaded).
"""

from pathlib import Path
import subprocess
import sys

# Node: start the server, print its endpoint, close it when stdin ends.
SERVER = r"""
const { chromium } = require(process.argv[1]);
// HARNESS_CHROME_HEADED=1: its windows show (tiled browser windows, on $DISPLAY);
// HARNESS_CHROME_PATH: that Chrome executable instead of the installed Google Chrome.
const options = { headless: process.env.HARNESS_CHROME_HEADED !== "1", chromiumSandbox: true, host: "127.0.0.1" };
if (process.env.HARNESS_CHROME_PATH) options.executablePath = process.env.HARNESS_CHROME_PATH;
else options.channel = "chrome";
chromium.launchServer(options).then(
  (server) => {
    process.stdout.write(JSON.stringify({ endpoint: server.wsEndpoint() }) + "\n");
    const stop = () => server.close().finally(() => process.exit(0));
    process.stdin.on("end", stop);
    process.stdin.on("error", stop);
    process.stdin.resume();
  },
  (error) => {
    process.stderr.write(`Could not start background Chrome. An installed Google Chrome is required: ${error}\n`);
    process.exit(1);
  });
"""


def command() -> list[str]:
    """The Node driver's command line that serves the shared Chrome."""
    from playwright._impl._driver import compute_driver_executable

    node, cli = compute_driver_executable()
    return [str(node), "-e", SERVER, str(Path(cli).parent)]


def main() -> int:
    # stdin, stdout and stderr are this process's: the server sees the same end of input.
    return subprocess.call(command())


if __name__ == "__main__":
    sys.exit(main())
