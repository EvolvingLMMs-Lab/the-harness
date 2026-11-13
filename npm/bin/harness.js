#!/usr/bin/env node
// The `harness` command of the npm package: runs the Python package shipped next to it
// (../python/harness, standard library only) with a Python 3.11 or newer found on this computer.
"use strict";

const { spawn, spawnSync } = require("node:child_process");
const path = require("node:path");

const MINIMUM = [3, 11];
const source = path.join(__dirname, "..", "python");

function version(command, args) {
  const probe = spawnSync(command, [...args, "-c", "import sys; print('%d.%d' % sys.version_info[:2])"], {
    encoding: "utf8",
    windowsHide: true,
  });
  if (probe.status !== 0 || !probe.stdout) return null;
  const [major, minor] = probe.stdout.trim().split(".").map(Number);
  return Number.isInteger(major) && Number.isInteger(minor) ? [major, minor] : null;
}

function recentEnough(found) {
  return found !== null && (found[0] > MINIMUM[0] || (found[0] === MINIMUM[0] && found[1] >= MINIMUM[1]));
}

// HARNESS_PYTHON names the interpreter; otherwise the first of these that is new enough.
function interpreter() {
  const named = process.env.HARNESS_PYTHON;
  const candidates = named
    ? [[named, []]]
    : process.platform === "win32"
      ? [["python", []], ["py", ["-3"]], ["python3", []]]
      : [["python3", []], ["python", []]];
  const seen = [];
  for (const [command, args] of candidates) {
    const found = version(command, args);
    if (recentEnough(found)) return { command, args };
    if (found) seen.push(`${[command, ...args].join(" ")} is ${found.join(".")}`);
  }
  // uv fetches a Python of its own when none is installed.
  if (!named && spawnSync("uv", ["--version"], { windowsHide: true }).status === 0) {
    return { command: "uv", args: ["run", "--no-project", "--python", MINIMUM.join("."), "python"] };
  }
  const detail = seen.length ? ` (${seen.join("; ")})` : "";
  console.error(
    `harness: Python ${MINIMUM.join(".")} or newer was not found${detail}.\n` +
      "Install it from https://www.python.org/downloads/ or install uv (https://docs.astral.sh/uv/),\n" +
      "or set HARNESS_PYTHON to the interpreter to use."
  );
  process.exit(1);
}

const { command, args } = interpreter();
const env = { ...process.env };
env.PYTHONPATH = env.PYTHONPATH ? source + path.delimiter + env.PYTHONPATH : source;

const child = spawn(command, [...args, "-m", "harness", ...process.argv.slice(2)], { stdio: "inherit", env });
// The terminal sends an interrupt to the whole process group: Python handles its own.
for (const signal of ["SIGINT", "SIGTERM", "SIGHUP"]) {
  process.on(signal, () => {
    if (signal !== "SIGINT") child.kill(signal);
  });
}
child.on("error", (error) => {
  console.error(`harness: could not start ${command}: ${error.message}`);
  process.exit(1);
});
child.on("exit", (code, signal) => {
  if (signal) {
    // Restore the default disposition before replaying the child's signal. Otherwise
    // our forwarding handler catches it again and Node exits with a success status.
    process.removeAllListeners(signal);
    process.kill(process.pid, signal);
  }
  else process.exit(code === null ? 1 : code);
});
