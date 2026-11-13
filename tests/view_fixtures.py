"""A computer-like worker with a screen, and its kernel session, for the view tests (the
kernel process imports this module from tests/)."""

import base64
import struct
import time
import zlib

from harness.core.worker import Tells


def picture(width=8, height=6, shade=0):
    """A small PNG as a data URL, its pixels of one grey `shade` (so pictures differ)."""
    def chunk(tag, data):
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    row = b"\x00" + bytes([shade % 256]) * (width * 3)
    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(row * height)) + chunk(b"IEND", b""))
    return "data:image/png;base64," + base64.b64encode(png).decode("ascii")


class ScreenEnvironment(Tells):
    """A worker with one view, `screen`: a command is a key press; every observe is
    counted and gives a picture shaded by the step. With `tells`, it tells the run what
    happens by itself (tell()). It has senses: a sense's code is a Python expression over
    `step`, computed with every state."""

    name = "screen"
    methods = ("profile", "state", "tick", "observe", "claim_outcome", "outcome", "tell_to",
               "sense", "senses", "drop_sense", "pause", "resume")

    def __init__(self, seconds=0.0, tells=False, pauses=False, references=()):
        self.seconds, self.step, self.observed, self.tells = seconds, 0, 0, tells
        self.references = list(references)   # the folders of what it gives to act with
        self.pauses, self.held = pauses, []   # (with `pauses`: what it was asked to hold and let go on)
        self.sense_code = {}

    def tools(self):
        return []

    def reset(self, task, seed):
        from harness.core.contracts import Observation

        self.step = 0
        return Observation("screen-1", 0, "Type the word.", self._state(), {"screen": picture(shade=0)})

    def _state(self):
        return {"step": self.step, "step_limit": 1000, "ended": False, "active_window": "Editor",
                "screen": [8, 6], "sensed": {name: eval(code, {"step": self.step})
                                             for name, code in self.sense_code.items()}}

    def call(self, name, arguments):
        if name == "profile":
            return {"kind": "desktop", "control_hz": 20.0, "step_seconds": None, "screen": [8, 6],
                    "senses": True, **({"tells": True} if self.tells else {}),
                    **({"pauses": True} if self.pauses else {}),
                    **({"references": self.references} if self.references else {})}
        if name == "pause":
            self.held.append(("pause", self.step, arguments.get("by")))
            return {"at": self.step}
        if name == "resume":
            self.held.append(("resume", arguments["held"]["at"], self.step))
            return {}
        if name == "sense":
            try:
                compile(arguments["code"], "sense", "eval")
            except SyntaxError as error:
                return {"defined": False, "error": str(error)}
            self.sense_code[arguments["sense"]] = arguments["code"]
            return {"defined": True, "value": self._state()["sensed"][arguments["sense"]], "error": None}
        if name == "senses":
            return {name: {"code": code, "value": self._state()["sensed"][name], "error": None}
                    for name, code in self.sense_code.items()}
        if name == "drop_sense":
            return {"removed": self.sense_code.pop(arguments["sense"], None) is not None}
        if name == "tell_to":
            return self._call_tell_to(**arguments)
        if name == "state":
            return self._state()
        if name == "tick":
            time.sleep(self.seconds)
            self.step += 1
            return {"executed": True, "state": self._state(),
                    "shield": {"verdict": "pass", "command": arguments["command"], "reasons": []}}
        if name == "observe":
            self.observed += 1
            return {"state": self._state(), "images": {"screen": picture(shade=self.step)}}
        if name == "claim_outcome":
            return {"token": "t"}
        if name == "outcome":
            return {"reward": 1.0, "success": True, "process_score": 100.0, "steps": self.step,
                    "terminated": False, "truncated": False}
        raise ValueError(name)


def screen_session(options):
    """The episode core over that worker, with type_text(count) and what it reports as text."""
    from harness.builtin.skills.agents import Agents
    from harness.builtin.skills.entries import Entries
    from harness.runtime.execution.session import EpisodeCore

    class ScreenSession(Agents, Entries, EpisodeCore):
        embodiment = "desktop"
        show_format = "png"

        def type_text(self, count, seconds=0.0):
            def command(state, tick):
                if seconds:
                    time.sleep(seconds)
                return {"key": "a"} if tick < count else None
            return self._execute("type_text", {"count": count}, command, 30, None, None)

        def get_state(self):
            return self.state

        def _evidence(self):
            return 'e1 edit "Body" value "hello world"'

        def _base_command(self, state):
            return {"key": None}

        def _tick(self, command, cameras=None):
            result = self.env.call("tick", episode_id=self.episode_id, step=self.state["step"], command=command)
            self.state = result["state"]
            return result

        def _reactive_view(self, state, tick):
            return {"step": state["step"]}

        def _outside(self, region, state):
            return False

    session = ScreenSession({**options, "skills": []})
    session.namespace.update(type_text=session.type_text, get_state=session.get_state,
                             spawn=session._entries.spawn, entries=session.entries,
                             output_of=session.output_of, delegate=session.delegate,
                             send_agent=session.send_agent)
    return session


def actions(body, allow_policy=False, allow_skills=False):
    """The action vocabulary of a direct-control run on that worker: a number of key presses."""
    return f"type_text({int(body)})"
