"""The worker of a bot body: a thin proxy between the worker protocol and the body's bridge
(a Node process holding a Mineflayer client) and its first-person pictures. It decides
nothing and knows nothing about the game.

    state      what the body reports of itself and what is near it, with what happened to
               it since the last reading (a death, a change of dimension, a restart)
    tick       a command: start code on the body (its job goes on in the game; it takes the
               body from the job before), stop it, hold. Code is started under a tag the
               caller chose; the state's "jobs" names the tags of the code that runs
    job        a started job (by its tag): its report
    tell       what happens to the body by itself is told to the run when it happens (the
               worker waits on the bridge's events; nothing is asked on a timer): the body's
               death, with what the game said, where the body is afterwards and the
               pictures of the 8 seconds before it
    attempt    the record of the attempt (one world from its spawn) as the game counted it:
               advancements and what the game told every player (the body's "told"
               events), with their game time, deaths, the commands typed; an attempt is
               clean until a command is typed in it
    start_over begin an attempt, giving up the one that runs: in a new world (where the run
               has a way to make one: the option `start_over`, a command of whoever owns the
               game server, which makes a world, has the server play it and prints
               {"world": its name} as JSON); with `kept` (the command then gets --kept), in a
               copy of the start that was kept. A run that is started while no game server
               answers has no attempt until this is called; where one answers, the world it
               plays is the first attempt. `attempts`: how many the run may begin (none
               given: any number); `given`: what the body is given as the first begins
               ({item: count}, by /give: the server obeys it where the body may use commands)
    keep_start keep the world as it is now, the body in it, as the start later attempts can
               begin from (the option `keep_start`, a command of the server's owner that
               copies the world: it gets --record JSON and prints {"seconds"} as JSON;
               `kept_info`, a command that prints that record again, for a run continued)
    observe    views: "view" the first-person picture now, "recent" the last seconds as a grid
    sense      senses (the worker protocol's): code the body computes with every state it
               reports, as the state's "sensed"; kept on the body like its routines
    pause      pausing (the worker protocol's): the code that has the body waits where it
               is while code of a higher priority has it, and goes on when resumed
"""

import base64
from http.client import HTTPConnection
import json
import os
import platform
import re
import subprocess
import threading
import time
import uuid
from urllib.parse import quote, urlsplit

from harness.sdk import WORKER_METHODS, BenchWorker, EpisodeCursor, Observation, load_embodiment

from benches.mineflayer import frames as pictures

# What a look may ask of the views beside their names (runtime/execution/session.py look).
VIEW_SETTINGS = ("a view's settings are: ago (seconds back from now, 0 or more), seconds (the stretch a grid "
                 "covers, more than 0), count (the pictures of a grid, 1 to 24), columns (of the grid, 1 to 8)")

NO_WINDOW = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
BODY_KEYS = ("health", "dead", "food", "oxygen", "level", "held", "armor", "inventory", "position", "velocity", "drop_below",
             "yaw", "pitch", "on_ground", "dimension", "time_of_day", "raining", "deaths", "sensed", "sense_errors",
             # What the code on the body asks to hold it with now (h.priority): the run's tick reads it.
             "priority")
NOTABLE = ("death", "respawn_or_dimension", "body_restarted")
# An attempt is there when its world is: a game server plays it. Before the first, what is said of the attempt,
# and what every call that acts on the body or the world is refused with.
NONE_BEGUN = {"number": 0, "begun": False,
              "why": "no attempt has begun: there is no world yet, and no body in one. start_over() begins the first"}
# What the agent is told with a death, and only then: how the body comes back.
DEAD = ("You can respawn it with respawn(): it is then at its spawn point. As the game is sold it has empty hands "
        "there and what it carried lies where it died, for five minutes; a server may keep the inventory instead.")
ADVANCEMENT = re.compile(r"(\S+) has (?:made the advancement|reached the goal|completed the challenge) \[(.+)\]")


def create_environment(**options):
    return BodyEnvironment(**options)


def data_url(jpeg: bytes) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(jpeg).decode()


class Bridge:
    """The body's bridge over one kept connection (its state is read every tick)."""

    def __init__(self, address):
        parts = urlsplit(address)
        self.host, self.port = parts.hostname, parts.port
        self.lock = threading.Lock()
        self.connection = None

    def call(self, method, path, body=None, timeout=10.0):
        payload = None if body is None else json.dumps(body).encode()
        headers = {"content-type": "application/json"} if payload is not None else {}
        with self.lock:
            for attempt in (0, 1):
                try:
                    if self.connection is None:
                        self.connection = HTTPConnection(self.host, self.port, timeout=timeout)
                    if self.connection.sock is not None:
                        self.connection.sock.settimeout(timeout)
                    self.connection.request(method, path, body=payload, headers=headers)
                    return json.loads(self.connection.getresponse().read() or b"{}")
                except (OSError, ValueError) as error:
                    if self.connection is not None:
                        self.connection.close()
                    self.connection = None
                    # Only a kept connection that went stale is tried again: a request that
                    # timed out may have been carried out (code started twice otherwise).
                    if attempt or isinstance(error, TimeoutError):
                        raise RuntimeError(f"the body's bridge at {self.host}:{self.port} does not answer") from None


class BodyEnvironment(BenchWorker):
    name = "mineflayer"
    tasks = ("free",)
    methods = (*WORKER_METHODS, "job", "stop", "save_routine", "remove_routine", "read_routine", "routines", "user_says", "nav", "body", "chat", "respawn", "job_by_id", "attempt", "start_over", "keep_start",
               "sense", "senses", "drop_sense", "pause", "resume")
    VIEWS = ("view", "recent")

    def __init__(self, bridge="http://127.0.0.1:8791", frames=None, instruction=None,
                 step_limit=5000000, embodiment="mineflayer", start_over=None, keep_start=None, kept_info=None, attempts=None, given=None,
                 player="minebot"):
        self._embodiment = load_embodiment(embodiment)
        self._screen = tuple(int(value) for value in self._embodiment["screen"])
        self._hz = float(self._embodiment["control_hz"])
        self._bridge = Bridge(bridge)
        self._frames = frames
        self._instruction = instruction or "Play."
        self._step_limit = int(step_limit)
        self._cursor = EpisodeCursor()
        self._last = None
        self._event_seq = 0
        self._happened = []        # notable events the agent has not been shown yet
        self._jobs = {}            # the caller's tag of started code -> the body's job
        self._start_over = list(start_over) if start_over else None   # the command that makes a new world
        self._keep_start = list(keep_start) if keep_start else None   # the command that keeps the world as a start
        self._kept_info = list(kept_info) if kept_info else None      # the command that says what start is kept
        self._kept = None                                             # what this run keeps as a start, once it does
        self._most = int(attempts) if attempts else None              # the attempts the run may begin (None: any number)
        self._given = {str(item): int(count) for item, count in (given or {}).items()}   # what the body has as its first attempt begins
        self._player = player
        self._attempts = self._found()
        self.new_outcome()

    # -- Worker protocol ---------------------------------------------------------

    def reset(self, task, seed):
        if task not in self.tasks:
            raise ValueError(f"This worker's tasks are {list(self.tasks)}, not {task!r}")
        self._cursor.start(uuid.uuid4().hex)
        self.new_outcome()
        self._event_seq = self._bridge.call("GET", "/events?after=0&limit=1").get("seq", 0)
        self._happened = []
        self._attempts = self._found()
        state = self._state()
        try:
            images = {"view": self._view()}
        except RuntimeError:   # a body may run without a window; a look then says why there is none
            images = {}
        return Observation(self._cursor.episode_id, 0, self._instruction, {**state, "task": task}, images)

    def close(self):
        self._cursor.invalidate()

    def _found(self) -> list:
        """The attempts there are when the worker starts or an episode begins: one, where a game server plays
        a world (the run was given its world, or is continued in the one it had); none where none does."""
        try:
            playing = bool(self._bridge.call("GET", "/server", timeout=5.0).get("answers"))
        except Exception:
            playing = False
        # (That world was not begun by this run: it is the server's, as it was.)
        return [self._new_attempt(1, began="the world the server plays, as it was when this session began")] if playing else []

    def _begun(self) -> None:
        """Refuse what acts on the body or the world while no attempt has begun."""
        if not self._attempts:
            raise ValueError(NONE_BEGUN["why"])

    def _call_profile(self):
        # The libraries the body's code calls (mineflayer and what it is made of): the bridge
        # runs on them and says where they are.
        libraries = (self._bridge.call("GET", "/state", timeout=5.0) or {}).get("libraries")
        return {**({"references": [libraries]} if libraries else {}), "kind": "botbody", "embodiment": self._embodiment["name"], "control_hz": self._hz, "max_hz": self._hz,
                "screen": list(self._screen), "step_limit": self._step_limit, "tasks": list(self.tasks),
                "benchmark": "mineflayer", "knowledge": "learned", "action_ids": True, "tells": True, "senses": True, "pauses": True,
                "situation": "dimension",
                "system": platform.system(), "physical": False, "execution": "mineflayer"}

    def _state(self, fresh=True):
        """The body's state; `fresh` False (a tick's reply) gives the one the period began with."""
        if fresh or self._last is None:
            body = self._bridge.call("GET", "/state", timeout=5.0)
            # While the body is away (it is being started again) its last reading stands.
            state = {**(self._last or {}), "screen": list(self._screen), "connected": bool(body.get("connected")),
                     "restarts": body.get("restarts", 0)}
            # (The routines are kept on the body's disk: there whether or not the body is in a world.)
            state["routines"] = body.get("skills", [])
            state.setdefault("jobs", [])
            if body.get("connected"):
                state.update({key: body.get(key) for key in BODY_KEYS})
                state["entities"] = body.get("entities", [])
                running = [*body.get("jobs_running", []), *body.get("jobs_paused", [])]   # (a paused job has not ended)
                state["jobs"] = [tag for tag, job in self._jobs.items() if job in running] or list(running)
                state["here"], state["space"] = [body["position"][axis] for axis in "xyz"], body.get("dimension")
            sequence = body.get("events_seq", self._event_seq)
            while sequence > self._event_seq:
                # What happened to the body that a player would have seen at once.
                answer = self._bridge.call("GET", f"/events?after={self._event_seq}&limit=400")
                heard = answer.get("events", [])
                self._event_seq = max([event["seq"] for event in heard], default=answer.get("seq", sequence))
                self._happened = (self._happened + [event for event in heard if event.get("kind") in NOTABLE])[-8:]
                for event in heard:
                    self._count(event)
                if len(heard) < 400:
                    break
            now = self._attempts[-1] if self._attempts else None
            state["attempt"] = ({"number": now["number"], "clean": now["clean"], "deaths": now["deaths"],
                                 "advancements": [item["name"] for item in now["advancements"]],
                                 "told": [item["what"] for item in now["told"]]} if now else dict(NONE_BEGUN))
            # Whether the agent can act: there is an attempt, and the body is alive. While it cannot, nothing
            # of the tree of reflexes is judged (the session's can_act).
            state["can_act"] = bool(self._attempts) and not state.get("dead")
            state["happened"] = [{"kind": event["kind"], "t": event["t"] / 1000.0,
                                  **({"dimension": event["dimension"]} if "dimension" in event else {}),
                                  **({"message": event["message"]} if event.get("message") else {}),
                                  **({"why": event["why"]} if event.get("why") else {})}
                                 for event in self._happened[-8:]]
            self._last = state
        return {**self._last, "step": self._cursor.step, "step_limit": self._step_limit, "ended": self._ended()}

    # -- What the body tells ----------------------------------------------------------

    def _call_tell_to(self, url, token, episode_id=None):
        answer = super()._call_tell_to(url, token, episode_id)
        if getattr(self, "_listening", None) is None:
            self._listening = threading.Thread(target=self._listen, name="body-events", daemon=True)
            self._listening.start()
        return answer

    def _call_nav(self, episode_id, what, kind=None, routine=None, code=None, args=None):
        """The hazards and route rules of the body's walking: define, undefine, avoid, unavoid, list.
        (What is defined is kept on the body's disk, with or without a world; in force is what a body in a
        world has.)"""
        self._check_episode(episode_id)
        if what in ("avoid", "unavoid"):
            self._begun()
        return self._bridge.call("POST", "/nav", {"what": what, "kind": kind, "name": routine, "code": code, "args": args})

    def _call_user_says(self, text):
        """What the user says to the agent while it runs: told to the run at once, as what
        the environment tells is (a wait ends, a reply being written is set aside and asked
        again with it), whatever program runs. {"told": whether a run listens}."""
        text = str(text or "").strip()
        if not text:
            raise ValueError("user_says(text): the message is empty")
        return {"told": self.tell([{"type": "text", "text": "The user says, while you work (your programs go on; "
                                                             "this is not a new task):\n" + text}], source="user")}

    def _listen(self):
        """Wait on the bridge for the body's deaths, and for code that has run as long as its
        call gave it, and tell the run of each as it happens."""
        died = []
        bridge = Bridge(f"http://{self._bridge.host}:{self._bridge.port}")   # (a connection of its own: it is held open)
        after = bridge.call("GET", "/events?after=0&limit=1").get("seq", 0)
        while True:
            try:
                answer = bridge.call("GET", f"/events?after={after}&kinds=death,over_time&wait_seconds=25&limit=20",
                                     timeout=40.0)
                for event in answer.get("events", []):
                    after = max(after, event["seq"])
                    if event.get("kind") == "over_time":
                        self.tell([{"type": "text", "text": (
                            f"Code on the body has run {float(event.get('seconds') or 0):g} s, the time its call "
                            "gave it, and goes on. code_running() says what it has done so far; "
                            "stop_routines() ends it.")}], source="body")
                        continue
                    try:
                        image, _ = self._recent(8.0, event["t"] / 1000.0 + 1.0)
                    except Exception:
                        image = None
                    said = f' The game said: "{event["message"]}".' if event.get("message") else ""
                    # The how-manieth death of this run it is, and of those with the same words.
                    died.append(event.get("message"))
                    same = died.count(event.get("message"))
                    said += (f" It is death {len(died)} of this run"
                             + (f", and number {same} with these words." if same > 1 else "."))
                    content = [{"type": "text", "text": f"The body died at {event.get('position')}.{said} {DEAD}"}]
                    if image:
                        content += [{"type": "text", "text": "The 8 s before it died, oldest picture first:"},
                                    {"type": "image_url", "image_url": {"url": image}}]
                    self.tell(content, source="body")
                after = max(after, 0)
            except Exception:
                time.sleep(2)

    # -- Attempts ----------------------------------------------------------------

    @staticmethod
    def _new_attempt(number, world=None, kept=None, began=None):
        """An attempt begins in a new world at its spawn, or (`kept`) in a copy of the start that was kept: the
        world is then as old as it was when it was kept, and the attempt's game time is counted from there."""
        return {"number": number, "world": world,
                "began": began or ("the start you kept" if kept else "a new world, at its spawn"),
                "world_age_at_start": kept["world_age_seconds"] if kept else 0.0,
                "clean": True, "advancements": [], "told": [], "deaths": 0, "died": [],
                "commands": 0, "commands_by_kind": {}, "first_command_at": None, "game_seconds": 0}

    @staticmethod
    def _clock(seconds):
        return f"{int(seconds) // 60}:{int(seconds) % 60:02d}"

    def _count(self, event):
        """One event of the body, into the record of the attempt that runs (none before the first)."""
        if not self._attempts:
            return
        now = self._attempts[-1]
        kind, age = event.get("kind"), event.get("age")
        # (The game time of an attempt: the world's own age, from the age it had when the attempt began.)
        seconds = max(0.0, age / 20.0 - now["world_age_at_start"]) if age is not None else None
        if seconds is not None:
            now["game_seconds"] = max(now["game_seconds"], seconds)
        at = self._clock(seconds) if seconds is not None else None
        if kind == "chat":
            found = ADVANCEMENT.match(event.get("message") or "")
            if found and found.group(1) == self._player:
                now["advancements"].append({"name": found.group(2), "at": at, "clean": now["clean"]})
        elif kind == "told":
            now["told"].append({"what": event.get("what"), "at": at, "clean": now["clean"]})
        elif kind == "death":
            now["deaths"] += 1
            now["died"].append({"at": at, "message": event.get("message")})
        elif kind == "command":
            word = (event.get("text") or "/").split()[0]
            now["commands"] += 1
            now["commands_by_kind"][word] = now["commands_by_kind"].get(word, 0) + 1
            if now["clean"]:
                now["clean"], now["first_command_at"] = False, at

    def _record(self, attempt):
        return {**attempt, "game_time": self._clock(attempt["game_seconds"]),
                "counts": ("everything in it" if attempt["clean"] else
                           f"what it reached before {attempt['first_command_at']} (its first command); from then on it is assisted")}

    def _call_attempt(self, episode_id, earlier=False):
        """The record of the attempt that runs; with `earlier`, of all attempts, oldest first."""
        self._check_episode(episode_id)
        self._state()
        if earlier:
            return {"attempts": [self._record(item) for item in self._attempts]}
        return self._record(self._attempts[-1]) if self._attempts else dict(NONE_BEGUN)

    def _call_keep_start(self, episode_id):
        """Keep the world as it is now as a start: everything in it, where the body stands, what it carries.
        A later start_over(kept=True) begins from it. One start is kept: a new one takes its place."""
        self._check_episode(episode_id)
        if not self._keep_start:
            raise ValueError("this run has no way to keep a start: it was given no command that copies the "
                             "server's world (the setting minebot.keep_start)")
        self._begun()
        state = self._state()
        if state.get("dead"):
            raise ValueError("the body is dead: a start is kept with a live body in it")
        body = self._bridge.call("GET", "/state", timeout=5.0)
        now = self._attempts[-1]
        kept = {"world_age_seconds": (body.get("world_age_ticks") or 0) / 20.0, "attempt": now["number"]}
        # (Kept beside the world: a worker started again for the same run takes it back, _kept_back.)
        made = subprocess.run(self._keep_start + ["--record", json.dumps(kept)], capture_output=True, text=True,
                              timeout=200, **NO_WINDOW)
        if made.returncode != 0:
            raise RuntimeError(f"the start was not kept: {(made.stderr or made.stdout)[-300:]}")
        answer = json.loads(made.stdout.strip().splitlines()[-1])
        self._kept = kept
        return {"kept": True, "in_attempt": now["number"],
                "at_game_time": self._clock(max(0.0, self._kept["world_age_seconds"] - now["world_age_at_start"])),
                "position": state.get("position"), "dimension": state.get("dimension"), "seconds": answer.get("seconds")}

    def _kept_back(self):
        """The start this run kept before its worker was started again (a run continued): what the option
        `kept_info` (a command) prints of it as JSON; None where the run has no such command or kept none."""
        if not self._kept_info:
            return None
        made = subprocess.run(self._kept_info, capture_output=True, text=True, timeout=30, **NO_WINDOW)
        try:
            record = json.loads(made.stdout.strip().splitlines()[-1]) if made.returncode == 0 else {}
        except (ValueError, IndexError):
            record = {}
        return record if "world_age_seconds" in record else None

    def _call_start_over(self, episode_id, kept=False):
        """Give the attempt up and begin a new one: a new world, the spawn, an empty inventory; or (`kept`) a
        copy of the start that was kept, the body in it as it was then.
        What the body keeps besides (its saved routines) stays. Returns the two records."""
        self._check_episode(episode_id)
        if not self._start_over:
            raise ValueError("the world of this server is not this body's to begin anew: the run was given no "
                             "command that makes a world (the setting minebot.start_over)")
        if kept and not self._kept:
            self._kept = self._kept_back()
        if kept and not self._kept:
            raise ValueError("no start is kept in this run: keep_start() keeps one")
        if self._most is not None and len(self._attempts) >= self._most:
            raise ValueError(f"this run is {self._most} attempt{'s' if self._most > 1 else ''}, and "
                             f"{'it has' if self._most == 1 else 'they have'} begun")
        self._state()
        given_up = self._record(self._attempts[-1]) if self._attempts else None
        self._bridge.call("POST", "/stop", {}, timeout=90.0)
        before = self._bridge.call("GET", "/events?after=0&limit=1").get("seq", self._event_seq)
        made = subprocess.run(self._start_over + (["--kept"] if kept else []), capture_output=True, text=True, timeout=400, **NO_WINDOW)
        if made.returncode != 0:
            raise RuntimeError(f"the new world did not come up: {(made.stderr or made.stdout)[-300:]}")
        world = json.loads(made.stdout.strip().splitlines()[-1])
        # The body is in the new world once it has joined a server since the old one was told to stop.
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            joined = self._bridge.call("GET", f"/events?after={before}&kinds=joined&limit=5", timeout=5.0).get("events")
            if joined and self._bridge.call("GET", "/state", timeout=5.0).get("connected"):
                break
            time.sleep(1)
        else:
            raise RuntimeError("the body did not join the new world")
        # What the run's first attempt begins with besides (the option `given`): given before the attempt's
        # record begins, so it is no command of the run.
        holds = dict(self._given) if not self._attempts and not kept else {}
        for item, count in holds.items():
            self._bridge.call("POST", "/chat", {"text": f"/give @s {item} {count}"})
        if holds:
            time.sleep(2)
        # What the body's log says of leaving the old world is not part of the new attempt.
        self._event_seq = self._bridge.call("GET", "/events?after=0&limit=1").get("seq", self._event_seq)
        self._happened = []
        self._attempts.append(self._new_attempt(len(self._attempts) + 1, world.get("world"), self._kept if kept else None))
        self._last = None
        # What every attempt begins with: the body in the world and alive; in a new world, at its spawn, at
        # full health and with empty hands (a kept start is as it was kept: what the body had then).
        for _ in range(40):
            body = self._bridge.call("GET", "/state", timeout=5.0)
            if body.get("connected") and body.get("health") is not None and body.get("inventory") is not None:
                break
            time.sleep(0.5)
        wrong = [what for what, ok in (("the body is in the world", body.get("connected")), ("it is alive", not body.get("dead")),
                                       *((("its health is full", body.get("health") == 20),
                                          ("its inventory is what it starts with" if holds else "its inventory is empty",
                                           (body.get("inventory") or {}) == holds)) if not kept else ()))
                 if not ok]
        if wrong:
            raise RuntimeError(f"the attempt began, but not as an attempt begins: it is not so that {', '.join(wrong)} "
                               f"(health {body.get('health')}, inventory {body.get('inventory')})")
        return {"given_up": given_up, "now": self._record(self._attempts[-1]), "state": self._state()}

    def _ended(self):
        return self._cursor.step is None or self._cursor.step >= self._step_limit

    def _view(self):
        """The first-person picture now. The game window watches as the body itself; a picture
        is given only while that holds: the window is on the body since its login, its own
        player stands where the body does, and the capture has a frame from the last second.
        Otherwise there is no picture, and the reason is said."""
        if not self._attempts:
            raise RuntimeError("no picture: " + NONE_BEGUN["why"])
        body = self._bridge.call("GET", "/state", timeout=5.0)
        window = body.get("window")
        if not window:
            raise RuntimeError("no picture: this body runs without a game window")
        if not (window.get("joined") and window.get("attached")):
            raise RuntimeError("no picture: the game window is not on the body")
        if not body.get("connected"):
            raise RuntimeError("no picture: the body is not in the world at this moment (it is being started again)")
        said, at = window.get("position"), body.get("position")
        if not said or (window.get("said_ms_ago") or 1e9) > 3000:
            raise RuntimeError("no picture: the game window has not said where its player is for 3 s")
        if sum((said[axis] - at[axis]) ** 2 for axis in "xyz") ** 0.5 > 3.0:
            raise RuntimeError("no picture: the game window's player is not where the body is")
        jpeg, _ = pictures.newest(1.0, folder=self._frames)
        if jpeg is None:
            raise RuntimeError("no picture: the capture of the game window has no frame from the last second")
        return data_url(jpeg)

    def _recent(self, seconds=8.0, until=None, count=6, columns=3):
        jpeg, ages = pictures.grid(seconds, until, count, folder=self._frames, columns=columns)
        return (data_url(jpeg), ages) if jpeg is not None else (None, [])

    def _screenshot(self):
        return {"view": self._view()}

    def _call_observe(self, episode_id, cameras=None, until=None, seconds=8.0, ago=0.0, count=6, columns=3):
        """The views asked for (all: the picture now), from the pictures kept (the last
        KEPT_MINUTES minutes, several a second). `ago`: how many seconds back the moment
        looked at is (`until`: that moment as a time; now). "view": the picture at that
        moment. "recent": `count` pictures spread over the `seconds` before that moment, as
        one grid of `columns`, oldest first."""
        self._cursor.check(episode_id, self._cursor.step)
        try:
            ago, seconds, count, columns = float(ago), float(seconds), int(count), int(columns)
        except (TypeError, ValueError):
            raise ValueError(VIEW_SETTINGS) from None
        if ago < 0 or seconds <= 0 or not 1 <= count <= 24 or not 1 <= columns <= 8:
            raise ValueError(VIEW_SETTINGS)
        moment = None if until is None and ago == 0 else (time.time() if until is None else float(until)) - ago
        images = {}
        for name in cameras or ("view",):
            if name == "view":
                if moment is None:
                    images["view"] = self._view()
                else:
                    jpeg = pictures.at(moment, folder=self._frames)
                    if jpeg is None:
                        raise RuntimeError(f"no picture: none is kept from {ago:g} s ago (the last "
                                           f"{pictures.KEPT_MINUTES} minutes are)")
                    images["view"] = data_url(jpeg)
            elif name == "recent":
                image, _ = self._recent(seconds, moment, count, columns)
                if image is not None:
                    images["recent"] = image
        return {"state": self._state(), "images": images}

    def _call_tick(self, episode_id, step, command, cameras=None, action_id=None, execution_id=None):
        self._cursor.check(episode_id, step)
        if self._ended():
            raise ValueError("The episode has ended; the command was not executed")
        kind = (command or {}).get("type", "noop")
        result = None
        if kind == "batch":
            # Codes on channels of their own, started in one period.
            for one in command.get("commands") or ():
                if (one or {}).get("type") not in ("run", "noop"):
                    raise ValueError(f"a batch holds run and noop commands, not {(one or {}).get('type')!r}")
            result = [self._start(one) for one in command.get("commands") or () if one.get("type") == "run"]
        elif kind == "run":
            result = self._start(command)
        elif kind == "stop":
            result = self._bridge.call("POST", "/stop", {}, timeout=90.0)
        elif kind != "noop":
            raise ValueError(f"a body's commands are run, batch, stop and noop, not {kind!r}")
        self._cursor.advance()
        receipt = {"executed": True, "shield": {"verdict": "PASS", "command": command, "reasons": []},
                   "state": self._state(fresh=kind != "noop"), "result": result}
        if action_id is not None:
            receipt["action_id"] = action_id
        return receipt

    def _start(self, command):
        """Start the code of a run command on the channels it says it uses (none: all of them).
        The bridge first ends a running job that uses one of them: that can take seconds (a
        restart of the body). (Before the first attempt there is no body to run it: the body's
        skill refuses the call before it comes here.)"""
        if not self._attempts:
            return {"job": None, "status": "error", "error": NONE_BEGUN["why"]}
        job = self._bridge.call("POST", "/run", timeout=90.0, body={
            "code": str(command["code"]), "args": command.get("args") or {}, "wait_seconds": 0,
            **({"limit_seconds": float(command["limit"])} if command.get("limit") else {}),
            **({"channels": list(command["channels"])} if command.get("channels") is not None else {})})
        if command.get("tag") and job.get("id"):
            self._jobs = {**dict(list(self._jobs.items())[-200:]), str(command["tag"]): job["id"]}
        return {"job": job.get("id"), "status": job.get("status"), "error": job.get("error")}

    def _evaluate(self):
        return {"success": None, "reward": None, "process_score": None, "steps": self._cursor.step,
                "reason": "The task's outcome is judged from the game, not by this worker."}

    # -- The body's own calls ------------------------------------------------------

    def _call_job(self, episode_id, id, wait_seconds=0):
        """The report of the code started under the tag `id`."""
        self._check_episode(episode_id)
        if id not in self._jobs:
            return {"status": "not run"}
        return self._bridge.call("GET", f"/job?id={quote(str(self._jobs[id]))}"
                                        f"&wait_seconds={float(wait_seconds):g}", timeout=float(wait_seconds) + 10)

    def _call_job_by_id(self, episode_id, id):
        """The report of the body's job `id` (the bridge's own name of it)."""
        self._check_episode(episode_id)
        return self._bridge.call("GET", f"/job?id={quote(str(id))}&wait_seconds=0", timeout=10)

    def _call_stop(self, episode_id, id=None):
        """End the code that runs on the body; with `id` (a tag), only if it is that code."""
        self._check_episode(episode_id)
        if id is not None:
            body = self._bridge.call("GET", "/state", timeout=5.0)
            if self._jobs.get(id) not in [*body.get("jobs_running", []), *body.get("jobs_paused", [])]:
                return {"stopped": False}
            return self._bridge.call("POST", "/stop", {"id": self._jobs[id]}, timeout=90.0)
        return self._bridge.call("POST", "/stop", {}, timeout=90.0)

    def _call_pause(self, episode_id, by=None, channels=None):
        """The code that runs on one of `channels` (None: on any) waits where it is (the worker
        protocol's pausing), and is told who takes them: what is given back to resume."""
        self._check_episode(episode_id)
        return self._bridge.call("POST", "/pause", {"by": by, **({"channels": list(channels)} if channels is not None else {})},
                                 timeout=10.0)

    def _call_resume(self, episode_id, held):
        self._check_episode(episode_id)
        paused = (held or {}).get("paused")
        ids = [paused] if isinstance(paused, str) else list(paused or [])
        if not ids:
            return {"resumed": []}
        return self._bridge.call("POST", "/resume", {"ids": ids}, timeout=90.0)

    def _call_save_routine(self, episode_id, routine, code):
        # (`name` is the worker protocol's own argument: a call's.)
        self._check_episode(episode_id)
        name = routine
        return self._bridge.call("POST", "/skill", {"name": name, "code": code})

    def _call_remove_routine(self, episode_id, routine, why=""):
        """Take a saved routine off the body; what it held is kept as a version."""
        self._check_episode(episode_id)
        if routine not in (self._bridge.call("GET", "/skills") or {}).get("skills", []):
            return {"error": "not saved"}
        return self._bridge.call("POST", "/skill/remove", {"name": routine, "why": str(why)})

    def _call_read_routine(self, episode_id, routine, version=None):
        self._check_episode(episode_id)
        name = routine
        return self._bridge.call("GET", f"/skill?name={quote(str(name))}"
                                 + (f"&version={quote(str(version))}" if version else ""))

    def _call_routines(self, episode_id):
        self._check_episode(episode_id)
        return self._bridge.call("GET", "/skills")

    def _call_body(self, episode_id):
        self._check_episode(episode_id)
        return self._bridge.call("GET", "/state")

    def _call_sense(self, episode_id, sense, code):
        # (`name` is the worker protocol's own argument: a call's.)
        self._check_episode(episode_id)
        return self._bridge.call("POST", "/sense", {"name": sense, "code": code})

    def _call_senses(self, episode_id):
        self._check_episode(episode_id)
        return self._bridge.call("GET", "/senses")

    def _call_drop_sense(self, episode_id, sense):
        self._check_episode(episode_id)
        return self._bridge.call("POST", "/sense/remove", {"name": sense})

    def _call_chat(self, episode_id, text):
        self._check_episode(episode_id)
        self._begun()
        return self._bridge.call("POST", "/chat", {"text": str(text)})

    def _call_respawn(self, episode_id):
        """Have the dead body respawn: {"respawned", "dead", "why"}."""
        self._check_episode(episode_id)
        self._begun()
        return self._bridge.call("POST", "/respawn", {}, timeout=20.0)
