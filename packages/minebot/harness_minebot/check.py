"""The body's own checks, without a model, against the game server the settings name:

    harness minebot check [--operator] [--only WORD] [--set KEY=VALUE]

Each check states the property it proves. The first group talks to a bridge of its own (the
body logs in as the settings say, so nothing else may be using that player meanwhile: what
this package started is stopped first); the last runs a scripted session through the
harness itself. The body moves a little, saves two routines named check_*, and is started
again several times; nothing in the world is built or broken.

`--operator`: also the checks that need the body to use commands there (they kill the body
and kick it): only on a server where that is yours to do.
"""

import argparse
import glob
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

from harness.sdk import UsageError, python_path

from . import provision, run as runs, stack
from .config import BODY, PACKAGE, data_dir, settings


SCRIPT = [
    """<python>
for page in ("body", "minecraft-1-16", "run-bot", "run-result", "run-routines"):
    guide(page)
print("pages read")
</python>""",
    """<python>
out = {}
if get_state().get('dead'):
    respawn()   # (a body that died while it stood there: the checks need a live one)
st = get_state()
out['state_keys'] = [k for k in ('health', 'food', 'position', 'dimension', 'held', 'inventory', 'entities', 'routines', 'jobs') if k in st]
out['save'] = bool(save_routine('check_echo', 'await sleep(200); return {got: args.x}'))
out['listed'] = 'check_echo' in routines()
r = routine('check_echo', {'x': 7}, seconds=10)
out['routine'] = (r.get('ended'), r.get('result'))
r = run_js("log('hi'); return 1 + 1", seconds=10)
out['run_js'] = (r.get('ended'), r.get('result'), r.get('logs'))
r = run_js('throw new Error("boom")', seconds=10)
out['run_js_error'] = (r.get('ended'), str(r.get('error'))[:40])
out['version'] = body().get('version')
print(out)
</python>""",
    "<finish>checked</finish>",
]


class Bridge:
    """A bridge of the checks' own, on a port and a routine store of its own."""

    def __init__(self, values):
        self.values = values
        self.port = int(values["bridge_port"]) + 2
        self.url = f"http://127.0.0.1:{self.port}"
        self.store = data_dir() / "check-store"
        self.process = None

    def __enter__(self):
        shutil.rmtree(self.store, ignore_errors=True)
        stack.logs_dir().mkdir(parents=True, exist_ok=True)
        env = stack.bridge_environment({**self.values, "bridge_port": self.port, "window": "off"},
                                       stack.game_version(self.values), store=self.store)
        self.log = (stack.logs_dir() / "bridge-check.log").open("wb")
        self.process = subprocess.Popen([str(provision.node()), str(BODY / "bridge.js")], cwd=BODY, stdout=self.log,
                                        stderr=self.log, stdin=subprocess.DEVNULL, env=env, **stack.QUIET)
        return self

    def __exit__(self, *exc):
        stack.end(self.process.pid)
        self.log.close()
        shutil.rmtree(self.store, ignore_errors=True)

    def call(self, path, body=None, timeout=120):
        if body is None:
            answer = stack.get(self.url + path, timeout=timeout)
            if answer is None:
                raise RuntimeError(f"the bridge did not answer {path}")
            return answer
        return stack.post(self.url + path, body, timeout=timeout)

    def run(self, code, limit=20, wait=60, args=None):
        return self.call("/run", {"code": code, "limit_seconds": limit, "wait_seconds": wait, "args": args or {}}, timeout=wait + 90)

    def state(self):
        return self.call("/state", timeout=5)

    def seq(self):
        return self.state()["events_seq"]

    def events(self, after):
        return self.call(f"/events?after={after}&limit=2000")["events"]

    def restarted_since(self, after):
        return [event for event in self.events(after) if event["kind"] == "body_restarted"]

    def in_world(self, seconds=60):
        deadline = time.time() + seconds
        while time.time() < deadline:
            try:
                if self.state().get("connected"):
                    return True
            except Exception:
                pass
            time.sleep(0.25)
        return False

    def tick_rate(self, seconds=2.0):
        first = self.state()["ticks"]
        time.sleep(seconds)
        return (self.state()["ticks"] - first) / seconds

    def chat(self, text):
        self.call("/chat", {"text": text})
        time.sleep(0.4)


def bridge_checks(b: Bridge, check, operator: bool) -> None:
    name = b.values["username"]

    @check("code runs", "code gets the bot, its return value and log lines come back, the body ticks at the game's rate")
    def _():
        r = b.run("log('hello', {a: 1}); return {name: bot.username, has: typeof bot.world.raycast}")
        assert r["status"] == "done" and r["ended_by"] == "itself", r
        assert r["result"]["has"] == "function" and r["logs"] == ['hello {"a":1}'], r
        rate = b.tick_rate()
        assert rate >= 18, f"{rate} ticks/s"
        thrown = b.run("throw new Error('boom')")
        assert thrown["status"] == "error" and "boom" in thrown["error"], thrown
        wrong = b.run("this is not code")
        assert wrong["status"] == "error" and "syntax" in wrong["error"].lower(), wrong
        return f"result {r['result']}, {rate:.0f} ticks/s, a throw and a syntax error are reported as errors"

    @check("code that never pauses", "a loop without an await cannot hold the body: the bridge keeps answering, ends it, the body is back")
    def _():
        before, began = b.seq(), time.time()
        r = b.run("while (true) {}", limit=60, wait=0)
        assert r["status"] == "running", r
        answered = 0
        while time.time() - began < 4:
            b.state()
            answered += 1
            time.sleep(0.5)
        r = b.call(f"/job?id={r['id']}&wait_seconds=30")
        took = time.time() - began
        assert r["status"] == "stopped" and "without a pause" in r["error"], r
        assert b.in_world() and len(b.restarted_since(before)) == 1
        return f"the bridge answered {answered} times during the loop; ended after {took:.1f} s; the body is back"

    @check("listeners that throw", "a listener that throws stops neither the physics nor the other listeners, and is reported without flooding")
    def _():
        before = b.seq()
        # (The listeners code leaves end with it: they are looked at while the code runs.)
        r = b.run("""
          let seen = 0
          bot.on('physicsTick', () => { throw new Error('tick boom') })
          bot.on('physicsTick', () => { seen++ })               // behind the one that throws
          bot._client.on('packet', () => { throw new Error('packet boom') })
          bot.on('physicsTick', async () => { throw new Error('async boom') })
          await sleep(4000)
          return seen""", limit=20, wait=0)
        assert r["status"] == "running", r
        time.sleep(0.5)
        rate = b.tick_rate(2.5)
        assert rate >= 18, f"{rate} ticks/s with throwing listeners"
        r = b.call(f"/job?id={r['id']}&wait_seconds=20")
        assert r["status"] == "done" and r["result"] > 40, r
        errors = [event for event in b.events(before) if event["kind"] == "listener_error"]
        kinds = {event["message"] for event in errors}
        assert {"tick boom", "packet boom", "async boom"} <= kinds, kinds
        assert len(errors) <= 12, f"{len(errors)} error events in a few seconds"
        return f"{rate:.0f} ticks/s; the listener behind the throwing one ran {r['result']} times; {len(errors)} error events for {sorted(kinds)}"

    @check("code that ignores the stop", "code that keeps timers and does not return is cut off from the body: after it is ended nothing of it moves the body")
    def _():
        r = b.run("""
          const me = bot
          setInterval(() => { me.setControlState('forward', true); me.setControlState('jump', true) }, 50)
          await new Promise(() => {})""", limit=1, wait=0)
        b.call("/stop", {})
        r = b.call(f"/job?id={r['id']}&wait_seconds=30")
        assert r["status"] == "stopped", r
        assert b.in_world()
        # (The body lands and is put where the server has it after its login: it is looked at once that is over.
        # Keys the old code still pressed would keep it moving through every look.)
        moved = None
        for _ in range(5):
            time.sleep(1.0)
            first = b.state()["position"]
            time.sleep(2.0)
            second = b.state()["position"]
            moved = ((first["x"] - second["x"]) ** 2 + (first["z"] - second["z"]) ** 2) ** 0.5
            if moved < 0.2:
                break
        held = b.run("return ['forward', 'jump', 'sprint'].filter(c => bot.getControlState(c))")
        assert moved < 0.2 and held["result"] == [], (moved, held["result"])
        return f"after the end the body moved {moved:.2f} blocks in 2 s and holds no key"

    @check("new code takes the body", "new code ends the code before it: code that lets go when told ends at once, code that does not is ended with the body's process")
    def _():
        before = b.seq()
        first = b.run("for (let i = 0; i < 300; i++) await sleep(100); return 'ran out'", limit=60, wait=0)
        second = b.run("return 'second'")
        first = b.call(f"/job?id={first['id']}")
        assert first["status"] in ("done", "stopped") and first["ended_by"] == "another job", first
        assert second["status"] == "done" and second["result"] == "second", second
        assert not b.restarted_since(before), "code that let go when told was ended with the body's process"
        third = b.run("await new Promise(() => {})", limit=60, wait=0)
        assert b.state()["jobs_running"] == [third["id"]]
        fourth = b.run("return 'fourth'")
        third = b.call(f"/job?id={third['id']}")
        assert third["status"] == "stopped" and third["ended_by"] == "another job", third
        assert fourth["status"] == "done" and fourth["result"] == "fourth", fourth
        assert len(b.restarted_since(before)) == 1
        return "code that let go ended without a restart; code that did not was ended by one; the new code ran each time"

    @check("physics that stop", "a body in the world whose physics no longer tick is started again")
    def _():
        before, began = b.seq(), time.time()
        assert b.run("bot.physicsEnabled = false; return 'off'")["status"] == "done"
        deadline = time.time() + 25
        while time.time() < deadline and not b.restarted_since(before):
            time.sleep(0.5)
        why = b.restarted_since(before)
        assert why and "physics" in why[0]["why"], why
        assert b.in_world()
        rate = b.tick_rate()
        assert rate >= 18, rate
        return f"restarted after {time.time() - began:.0f} s ({why[0]['why']}); {rate:.0f} ticks/s again"

    @check("a body process that dies", "when the body's process ends by itself the code on it is reported as stopped and the body comes back")
    def _():
        before = b.seq()
        r = b.run("setTimeout(() => process.exit(1), 100); await sleep(5000); return 'never'", limit=30)
        assert r["status"] == "stopped" and "ended" in r["error"], r
        assert b.in_world() and b.restarted_since(before)
        assert b.run("return 'back'")["result"] == "back"
        return "a process that ended was followed by a restart; code runs again"

    @check("saved routines", "a routine is saved, called, overwritten with its old version kept, refused when it does not parse, and there after a restart")
    def _():
        assert b.call("/skill", {"name": "check_one", "code": "return {v: 1, got: args.x}"}).get("saved")
        assert b.call("/skill", {"name": "check_two", "code": "const r = await skills.check_one({x: args.x}, log, signal); return {via: r}"}).get("saved")
        r = b.run("return await skills.check_two({x: 7}, log, signal)")
        assert r["result"] == {"via": {"v": 1, "got": 7}}, r
        saved = b.call("/skill", {"name": "check_one", "code": "return {v: 2, got: args.x}"})
        assert len(saved["versions"]) == 1, saved
        assert "syntax" in b.call("/skill", {"name": "check_one", "code": "return {{{"}).get("error", "")
        old = b.call(f"/skill?name=check_one&version={saved['versions'][0]}")
        assert old["code"] == "return {v: 1, got: args.x}", old
        b.run("setTimeout(() => process.exit(1), 50); await sleep(3000)", limit=10)
        assert b.in_world()
        r = b.run("return await skills.check_two({x: 9}, log, signal)")
        assert r["result"] == {"via": {"v": 2, "got": 9}}, r
        return "saved, called from another routine, the new version runs, the old one is readable, bad code refused, all there after a restart"

    if not operator:
        return

    @check("a kick", "when the server drops the body it comes back by itself (--operator: the body kicks itself)")
    def _():
        before = b.seq()
        b.chat(f"/kick {name} checking")
        deadline = time.time() + 20
        while time.time() < deadline and not b.restarted_since(before):
            time.sleep(0.5)
        assert b.restarted_since(before), "a kick was not followed by a restart (may the body use commands here?)"
        assert b.in_world() and b.run("return 'back'")["result"] == "back"
        return "a kick from the server was followed by a restart; code runs again"

    @check("death", "a death is reported with the game's own words, and the body stays dead until it is told to respawn (--operator: the body kills itself)")
    def _():
        before, deaths = b.seq(), b.state()["deaths"]
        b.chat(f"/kill {name}")
        deadline, got = time.time() + 10, []
        while time.time() < deadline and not got:
            got = [event for event in b.events(before) if event["kind"] == "death"]
            time.sleep(0.3)
        assert got and got[0].get("message", "").startswith(name + " "), got
        time.sleep(1.0)
        assert b.state().get("dead"), "the body did not stay dead"
        answer = b.call("/respawn", {})
        assert answer.get("respawned") and b.state()["deaths"] == deaths + 1, answer
        return f"death with \"{got[0]['message']}\"; dead until respawn(); deaths {deaths} -> {deaths + 1}"


def harness_check(values, check) -> None:
    @check("through the harness", "a scripted session reaches the body through the worker: state, a saved routine, code with its result, logs and errors")
    def _():
        folder = Path(tempfile.mkdtemp(prefix="minebot-check-"))
        try:
            options = stack.worker_options(values, instruction="Check the body's calls.")
            assert stack.up(values, store=folder / "store", options=options, log=lambda message: None), "the body did not come up"
            (folder / "script.json").write_text(json.dumps(SCRIPT), encoding="utf-8")
            (folder / "library").mkdir()
            (folder / "config.toml").write_text(
                f'description = "The checks of the bot body"\ninclude = ["{runs.forward(runs.BASE)}"]\n'
                f'endpoint = "{stack.endpoint(values)}"\n\n[budget]\nmax_model_calls = 8\nmax_wall_seconds = 300\n\n'
                f'[overrides.agent.botbody.runtime]\nlibrary = {{ path = "{runs.forward(folder / "library")}", learn = "off" }}\n'
                # (The scripts are not a model's: they are held to neither a purpose nor the method of the tree.)
                'purpose = "optional"\nreflex_method = "optional"\n',
                encoding="utf-8", newline="\n")
            done = subprocess.run([sys.executable, "-m", "harness", "program", str(folder / "config.toml"), "--script",
                                   str(folder / "script.json"), "--output", str(folder / "trace")], capture_output=True, text=True,
                                  timeout=400, env={**os.environ, "PYTHONPATH": python_path(), "PYTHONUTF8": "1"}, **stack.QUIET)
            traces = glob.glob(str(folder / "trace" / "**" / "events.jsonl"), recursive=True)
            assert traces, f"no trace (exit {done.returncode}): {done.stdout[-300:]} {done.stderr[-300:]}"
            rows = [json.loads(line) for line in open(traces[0], encoding="utf-8") if line.strip()]
            printed = [row.get("text", "") for row in rows if row.get("event") == "program_output"]
            found = next((eval(text.strip().splitlines()[-1], {"__builtins__": {}}) for text in printed
                          if text.strip().splitlines() and text.strip().splitlines()[-1].startswith("{")), None)
            errors = [str((row.get("result") or {}).get("error"))[-400:] for row in rows if row.get("event") == "cell"
                      and (row.get("result") or {}).get("status") not in ("ok", "finished")]
            assert found, f"the program printed nothing to read: {printed[-2:]}; errors: {errors}"
            assert len(found["state_keys"]) == 9 and found["save"] and found["listed"], found
            assert found["routine"] == ("by itself", {"got": 7}), found
            assert found["run_js"] == ("by itself", 2, ["hi"]), found
            assert found["run_js_error"][0] == "an error" and "boom" in found["run_js_error"][1], found
            return f"the calls answered as a session sees them; the server runs {found['version']}"
        finally:
            stack.down(log=lambda message: None)
            shutil.rmtree(folder, ignore_errors=True)


def main(argv) -> int:
    parser = argparse.ArgumentParser(prog="harness minebot check", description="The body's own checks, without a model, "
                                     "against the game server the settings name")
    parser.add_argument("--operator", action="store_true", help="also the checks that kick and kill the body by command")
    parser.add_argument("--only", metavar="WORD", help="only the checks whose name holds WORD")
    parser.add_argument("--set", dest="sets", action="append", default=[], metavar="KEY=VALUE")
    args = parser.parse_args(argv)
    overrides = {}
    for item in args.sets:
        key, has, value = item.partition("=")
        if not has:
            raise UsageError(f"--set takes KEY=VALUE, not {item!r}")
        overrides[key.strip().removeprefix("minebot.")] = value
    try:
        values = settings(overrides)
    except ValueError as error:
        raise UsageError(str(error)) from None
    if runs.live_run():
        print(f"the run {runs.live_run()} is live: checks do not enter a live run")
        return 1
    results = []

    def check(name, proves):
        def wrap(function):
            if args.only and args.only not in name:
                return function
            started = time.time()
            try:
                text, ok = function(), True
            except AssertionError as error:
                text, ok = f"FAILED: {error}", False
            except Exception as error:   # a check that cannot run has not passed
                text, ok = f"ERROR: {type(error).__name__}: {error}", False
            results.append((name, ok))
            print(f"{'ok  ' if ok else 'FAIL'} {name}  [{time.time() - started:.0f} s]\n       proves: {proves}\n       {text}", flush=True)
            return function
        return wrap

    stack.down(log=lambda message: None)
    provision.ensure(lambda message: print(message, file=sys.stderr, flush=True))
    try:
        with Bridge(values) as bridge:
            if not bridge.in_world(300 if values["auth"] == "microsoft" else 60):
                print(f"the body did not get into the world at {values['host']}:{values['port']}; see "
                      f"{stack.logs_dir() / 'bridge-check.log'}")
                return 1
            if bridge.state().get("dead"):
                bridge.call("/respawn", {})   # (a body that died while it stood there: the checks need a live one)
                time.sleep(2.0)
            bridge_checks(bridge, check, args.operator)
    except RuntimeError as error:
        print(str(error))
        return 1
    harness_check(values, check)
    failed = [name for name, ok in results if not ok]
    print(f"\n{len(results) - len(failed)} of {len(results)} checks passed" + (f"; failed: {failed}" if failed else ""))
    return 1 if failed or not results else 0
