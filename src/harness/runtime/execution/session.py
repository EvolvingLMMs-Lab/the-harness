"""The episode core: the session skeleton every embodiment's kernel session is.

A kernel session connects to a worker, keeps the state it reports, the model clients of the
skills (VLM, pointer, verifier, segmenter) and the units of the model
(runtime/execution/entries.py), and runs their bounded executions on its tick
(runtime/tick.py): at each step the reactive layer's rules that stop are asked, the
termination conditions are checked, and one command goes to the worker, whose shield passes
or rejects it. An execution ends with an event; one that is not nominal goes to the rules
that answer it (on()), and one nobody answers ends the unit and reaches the model. What a
unit gathers for the model (pictures, events, views) is its own: its box.

An embodiment (a robot, a computer, a game) is a worker that serves the worker protocol
(core/worker.py WORKER_METHODS) behind a shield (runtime/safety/shield.py CommandShield), and a
session that subclasses EpisodeCore and says what a step's command is and how it reaches the
worker (_tick), the command that leaves everything as it is (_base_command), what reactive
code observes (_reactive_view), when a command leaves an execution's scope (_outside), what
a trace samples, and the guard actions it takes itself. With channels it also says how a
command takes them and how the tick merges the parts (_plan, _merge, _still, _admit,
_channels_of, _channel_of_reason). The kernel's session class is the embodiment's session
plus the mixin of every skill for that kind (session_class()); its namespace holds the
exports of the skills enabled for the run (runtime/execution/skills.py).

Bootstrap: harness.runtime.execution.kernel --bootstrap harness.runtime.execution.session:create_session
Options: {"endpoint", "episode_id", "embodiment", "skills", "reactive_budget_ms", "reaction_delay_ms", "observer",
          "default_max_seconds", "vlm", "pointer", "verifier", "segmenter", "vision", "mcp",
          "memory", "library", "agent_skills", "policies", "world_models"}, and an embodiment's
          own (a robot's: "strategy_first", "policy_progress_seconds", harness_robot/session.py)
"""

import importlib
import json
import math
from pathlib import Path
import threading
import time

from harness.core import spans
from harness.core.remote import RemoteEnvironment
from harness.embodiments import KINDS
from harness.runtime.events import EpisodeEnded, Escalation, Event, ExecutionTrace
from harness.runtime.execution import control
from harness.runtime import events as ev
from harness.runtime.decision.model import USAGE
from harness.runtime.execution.entries import ClosedLoop, Tree
from harness.runtime.reactive.rules import HOLD, STOP, ReactiveFault, call_reactive
from harness.runtime.reactive.tree import Reflexes, _staging, fault_event
from harness.runtime.tick import Preempted, Tick, delay_ticks, driving


# The session of each embodiment kind, as "module:Class" (embodiments.KINDS).
SESSIONS = {name: kind.session for name, kind in KINDS.items()}
# The seconds between two reports of the state to the host (the `state` note).
STATE_NOTE_SECONDS = 1.0


# The page on how a tree of reflexes is designed and tried (Session.reflex_method), and what
# set_reflex says when it is called before that page was read, or without the node's trial.
METHOD_PAGE = Path(__file__).resolve().parents[2] / "builtin" / "prompts" / "shared" / "reflex-method.md"
# The pages of instructions a program reads on demand (Session.guide): the core prompt keeps
# what every reply needs and names these for the rest, as Claude Code keeps a skill's text
# out of its prompt until the skill is used.
GUIDES = {"tree": METHOD_PAGE, "units": METHOD_PAGE.with_name("units.md")}
ACTION_NEEDED = ("Nothing was set: every node does something. do= is the node's program, a function that "
                 "answers its situation; a node above others has one too, for what none of them answers.")
CONDITION_FAILS = ("Nothing was set: the node's condition cannot be judged on the state as it is now. It raised "
                   "{reason}. A condition returns whether the agent is in the situation on every state it can "
                   "be given.")
METHOD_FIRST = ("Nothing was set: read how a tree of reflexes is designed and set first. guide(\"tree\") "
                "returns the page; print it, read it, then set the tree.")
TRIAL_IS_A_FUNCTION = "test= is a function that brings the node's situation about; it is run at once"
# How long a trial waits for the node to have its turn after its function returned.
TRIAL_SECONDS = 10.0


class EpisodeCore:
    """The session skeleton every embodiment and skill builds on: the worker connection and
    profile, the state, the model clients, the reactive layer (rules, facts, answers to
    events), the tree of entries and bounded executions on the tick. An embodiment's session
    subclasses it (see the module docstring); its `namespace` holds the enabled skills'
    exports."""

    # The embodiment kind of this session (embodiments.KINDS).
    embodiment = None
    # Guard actions the session takes itself (when(predicate, action)); any other action
    # is an event name.
    guard_actions = (STOP, HOLD)
    # Executions that change nothing: the run lets them act whatever it refuses (_refuses).
    still_executions = ("hold",)
    # The channels of the embodiment ({name: channel}, runtime/tick.py); none: it is one
    # resource, and executions take turns on it.
    channels = {}
    hold_fields = ()
    observation_event_kinds = frozenset()
    # How show() encodes an array: "png" (exact pixels) or "jpeg" (camera pictures).
    show_format = "png"

    def __init__(self, options, *, environment=None):
        self.env = environment if environment is not None else RemoteEnvironment(
            options["endpoint"], timeout=float(options.get("timeout_seconds", 300)),
            host_controls=options.get("host_controls", ()), relay=options.get("worker_relay"))
        self.episode_id = options["episode_id"]
        self.profile = self.env.call("profile")
        self.hz = float(self.profile.get("control_hz", 1))
        self.default_max_seconds = float(options.get("default_max_seconds", 30.0))
        self.reactive = Reflexes(float(options.get("reactive_budget_ms", 5.0)) / 1000.0, self.guard_actions)
        # Whether a node is set with its trial, after the page on how a tree is made was read
        # (runtime.reflex_method; see set_reflex).
        self._method_required = options.get("reflex_method", "required") == "required"
        self._method_read = False
        self.reactive.tell_first = self._method_required
        # A rule on time is judged at the environment's rate unless it names a period,
        # never faster than the environment can be driven (runtime/tick.py driving).
        bound = driving(self.profile)[0]
        self.reactive.period, self.reactive.min_period = 1.0 / self.hz, 1.0 / (bound or self.hz)
        # What the run knows, shared by its programs and rules.
        self.facts = Facts(self._facts_changed, options.get("facts"))
        # Between an observation and the action decided on it (runtime/tick.py).
        self.reaction_delay_ms = float(options.get("reaction_delay_ms") or 0.0)
        delay_ticks(self.reaction_delay_ms, self.hz)
        # The world memory's observer as the run gives it (the world package's skill reads it).
        self.observer = options.get("observer")
        # MCP tool servers for the mcp skill: {name: {"url", "description"}}.
        self.mcp_servers = dict(options.get("mcp") or {})
        # Agent Skills the user installed in the app: {name: {"description", "path"}}.
        self.agent_skills = dict(options.get("agent_skills") or {})
        # Learned model services belong to the episode, not to a robot session.
        self.policies = dict(options.get("policies") or {})
        self._policy_clients = {}
        self.world_models = dict(options.get("world_models") or {})
        # Other environments taken into this conversation, by name (runtime/execution/attached.py),
        # and the names the namespace gained or gave up since the last cell ended (the kernel
        # keeps its API in step).
        self._attached = {}
        self._api_changes = {}
        # The model's units (runtime/execution/entries.py). The reflexes a unit sets are the
        # model's: they outlive the unit.
        self._entry_tree = Tree(self)
        self.reactive.view = lambda: self._view(self.state, 0)
        # Latest views of a running controller that servos on images.
        self._live = None
        self.state = self.env.call("state", episode_id=self.episode_id)
        self._embodiment_setup(options)
        # Success verifier (App. E, Tab. 5): a separate model a program may ask.
        self.verifier = image_role(options.get("verifier"), "verifier")
        self.vision = image_role(options.get("vlm"), "vlm")
        # Open-vocabulary pointing (Molmo2 in the paper); without it point_to uses the vlm.
        self.pointer = image_role(options.get("pointer"), "pointer")
        self.segmenter = None
        if options.get("segmenter"):
            self.segmenter = service_client(options["segmenter"])
        # Generic perception for a game learned from its pictures (skills/vision).
        self.vision_service = None
        if options.get("vision"):
            self.vision_service = service_client(options["vision"])
        # The run's library and its learning settings ({"directory", "settings"}), for
        # in-context learning (skills/learning).
        self.library_given = dict(options.get("library") or {})
        # The practice sandbox of an active run whose environment has one ({"what", "ops"}:
        # the bench's [sandbox]); absent in every other run (skills/learning `sandbox`).
        self.sandbox_given = dict(options.get("sandbox") or {})
        # The skills this kernel exposes, as the configuration resolved them
        # (config/agent.py resolve_for).
        from harness.runtime.execution.skills import namespace, reporters

        self.skills = list(options["skills"])
        self.namespace = {
            "__name__": "__program__", **namespace(self, self.skills),
            # The reactive layer: one tree, one call that puts a node into it (runtime/reactive/tree.py).
            "set_reflex": self.set_reflex, "drop_reflex": self.reactive.drop, "reflexes": self.reactive.listing,
            "reflex_method": self.reflex_method, "guide": self.guide,
            "facts": self.facts, "at_priority": self.at_priority, "until": self._entries.until,
            "run_controller": self.run_controller,
            # The host switches skills on between programs (sub-agents the user turned on).
            "__load_skills__": self.load_skills,
            # The host reads what the environment reports as text for the verifier.
            "__evidence__": lambda: print(self._evidence()),
        }
        self._reporters = reporters(self.skills)
        # The views of the environment and how the model gets them (the run's "views"):
        # "demand", the model looks itself (look, watch); else the run sends them with
        # every turn (a configuration that declares runtime.cameras) and nothing is added.
        views = dict(options.get("views") or {})
        self._views = {"cameras": list(views.get("cameras") or ()), "watch": None}
        if views.get("mode") == "demand":
            self.namespace.update(look=self.look, watch=self.watch_views, unwatch=self.unwatch, unpin=self.unpin)
        if self.profile.get("senses"):
            # The environment computes values the model defines, in its own language (senses).
            self.namespace.update(sense=self.sense, senses=self.senses, drop_sense=self.drop_sense)
        self._embodiment_ready(options)
        self.reactive.wake_observer = self._ticker.judge

    # The state: the tree of reflexes is judged when it changes (runtime/reactive/tree.py).

    @property
    def state(self):
        return self.__dict__.get("_state")

    @state.setter
    def state(self, value):
        self.__dict__["_state"] = value
        self._note_changes(value)
        # The host keeps the state as it was last reported (the `state` note, at most every
        # STATE_NOTE_SECONDS): what the model is told with every call (runtime/task/run.py _ambient).
        now = time.monotonic()
        if value and now - self.__dict__.get("_state_noted", 0.0) >= STATE_NOTE_SECONDS:
            self.__dict__["_state_noted"] = now
            spans.note("state", state=value)
        self._facts_changed()

    def _facts_changed(self):
        tick, layer = self.__dict__.get("_tick_loop"), self.__dict__.get("reactive")
        if tick is not None and layer is not None and layer.reads_changes():
            tick.judge()

    def _view(self, state, tick):
        """What rules, controllers and until predicates observe: the embodiment's view
        (_reactive_view) with the run's facts as "facts", and what a state alone does not
        show: what each thing it reports was before it last changed ("was") and for how
        many seconds it has not changed ("unchanged"), the senses under "sensed" in both;
        and the units that run ("units": each {"name", "kind", "reflex", "priority",
        "seconds"})."""
        view = self._reactive_view(state, tick)
        if isinstance(view, dict):
            view.setdefault("facts", self.facts.view())
            if isinstance(state, dict) and "sensed" in state:
                view.setdefault("sensed", state["sensed"])
            was, unchanged, now = {"sensed": {}}, {"sensed": {}}, time.monotonic()
            for key, (_, since, before) in list(self.__dict__.get("_changes", {}).items()):
                if isinstance(key, tuple):
                    was["sensed"][key[1]], unchanged["sensed"][key[1]] = before, now - since
                else:
                    was[key], unchanged[key] = before, now - since
            view.setdefault("was", was)
            view.setdefault("unchanged", unchanged)
            tree, wall = self.__dict__.get("_entry_tree"), time.time()
            view.setdefault("units", [
                {"name": unit.name, "kind": unit.kind, "reflex": unit.rule, "priority": unit.rank,
                 "seconds": wall - unit.started} for unit in (tree.running() if tree is not None else ())])
        return view

    def _note_changes(self, state) -> None:
        """Keep, for each thing the state reports (and each sense), its value, when it last
        changed and what it was before: what a condition needs to see that something
        changes, or that it does not."""
        if not isinstance(state, dict):
            return
        seen, now = self.__dict__.setdefault("_changes", {}), time.monotonic()

        def note(key, value):
            kept = seen.get(key)
            if kept is None:
                seen[key] = (value, now, None)
                return
            try:
                same = bool(kept[0] == value)
            except Exception:
                same = False
            if not same:
                seen[key] = (value, now, kept[0])

        for key, value in state.items():
            if key == "sensed" and isinstance(value, dict):
                for name, sensed in value.items():
                    note(("sensed", name), sensed)
            else:
                note(key, value)

    # Senses: values the environment computes itself, in its own language, each time it
    # reports its state (a worker whose profile says "senses": core/worker.py). What a
    # condition cannot read from the reported state and may not ask for (it makes no
    # calls) is computed where the environment is, by code the model defines, and reported
    # as state["sensed"][name]: one definition serves conditions and programs alike.

    def sense(self, name, code):
        """Have the environment compute `code` (in its own language; its page says which,
        and what the code has in scope) each time it reports its state, as
        view["sensed"][name]. Returns {"name", "value" (as computed now), "error"}."""
        answer = self.env.call("sense", episode_id=self.episode_id, sense=str(name), code=str(code))
        if answer.get("defined") is False:
            raise ValueError(f"sense {name!r} was not defined: {answer.get('error')}")
        self._observe()
        return answer

    def senses(self):
        """The senses defined: {name: {"code", "value", "error"}}."""
        return self.env.call("senses", episode_id=self.episode_id)

    def drop_sense(self, name):
        """Remove the sense `name`."""
        answer = self.env.call("drop_sense", episode_id=self.episode_id, sense=str(name))
        self._observe()
        return answer

    # What the unit that runs the calling code gathered for the model (its box).

    def _box(self):
        return self._entries.current().box

    @property
    def _attachments(self):
        return self._box().attachments

    @_attachments.setter
    def _attachments(self, value):
        self._box().attachments = value

    @property
    def _events(self):
        return self._box().events

    @_events.setter
    def _events(self, value):
        self._box().events = value

    @property
    def _event_counts(self):
        return self._box().event_counts

    @_event_counts.setter
    def _event_counts(self, value):
        self._box().event_counts = value

    @property
    def _looks(self):
        return self._box().looks

    @_looks.setter
    def _looks(self, value):
        self._box().looks = value

    def _evidence(self) -> str:
        """What this environment reports as text about where it stands, as evidence for a
        claim beside its state and views (a window's elements, a page's text). An
        embodiment's skills say what; none by default."""
        return ""

    def _embodiment_setup(self, options):
        """What the embodiment's session keeps besides the core's, set before the skills'
        namespace is built (the profile and the first state are there)."""

    def _embodiment_ready(self, options):
        """What the embodiment's session sets once the skills' namespace is built (it may
        read `skills`), before the tick runs."""

    def show(self, what, caption=""):
        """Attach an observation (each of its pictures) or an RGB array (a crop, say) to the
        next message you receive."""
        urls = getattr(what, "_urls", None)
        if isinstance(urls, dict):
            for camera, url in urls.items():
                name = (caption or camera) if camera == "screen" else f"{caption} {camera}".strip()
                self._attachments.append({"caption": name, "image_url": url})
            return
        from harness.core.codec import image_data_url

        try:
            url = image_data_url(what, self.show_format)
        except ValueError as error:
            raise ValueError(f"show() takes an observation or an HxWx3 RGB array ({error})") from None
        self._attachments.append({"caption": caption, "image_url": url})

    # Views on the model's demand.

    def _camera_names(self, cameras):
        known = self._views["cameras"]
        if not known:
            raise RuntimeError("This environment has no view to look at: read its state and what its calls return")
        names = list(known) if cameras is None else [cameras] if isinstance(cameras, str) else list(cameras)
        unknown = [name for name in names if name not in known]
        if unknown or not names:
            raise ValueError(f"no view {unknown or names}; this environment has {', '.join(known)}")
        return names

    def look(self, camera=None, region=None, keep=None, pin=None):
        """Put a view of the environment in your next turn, with this program's result:
        all its views, one by name, or the part region=(x, y, width, height) of it in the
        view's pixels. Nothing is shown unless a program looks. A view stays for your next
        reply only; keep=N keeps the views of the last N programs in sight, pin="name"
        keeps this one until unpin("name"). Returns what it saw (.state, and an image
        show() takes)."""
        names = self._camera_names(camera)
        data = self.env.call("observe", episode_id=self.episode_id, cameras=names)
        images = data.get("images") or {}
        if isinstance(data.get("state"), dict):
            self.state = data["state"]
        if region is not None:
            region = [int(value) for value in region]
            if len(region) != 4 or region[2] <= 0 or region[3] <= 0:
                raise ValueError("region is (x, y, width, height) in the view's pixels")
        seen = {}
        for name in names:
            if name not in images:
                continue
            url = images[name] if region is None else _cropped(images[name], region, self.show_format)
            seen[name] = url
            self._looks = [item for item in self._looks
                           if (item["camera"], item.get("region"), item.get("pin")) != (name, region, pin)]
            self._looks.append({"camera": name, "image_url": url, **({"region": region} if region else {}),
                                **({"pin": str(pin)} if pin else {})})
        if keep is not None:
            self.keep_views(keep)
        return Looked(self.state, seen)

    def keep_views(self, keep):
        if isinstance(keep, bool) or int(keep) < 1 or int(keep) > 20:
            raise ValueError("keep is how many programs' views stay in sight: 1 to 20")
        spans.note("views", action="keep", keep=int(keep))

    def watch_views(self, cameras=None, keep=None):
        """From now on the views (all, or those named) come with every program's result,
        until unwatch(). For work that is seen, not read: a game, a moving scene."""
        names = self._camera_names(cameras)
        if keep is not None:
            self.keep_views(keep)
        self._views["watch"] = {"cameras": names}
        spans.note("views", action="watch", cameras=names)
        return names

    def unwatch(self):
        """Stop watch(): views come again only when a program looks."""
        watching, self._views["watch"] = self._views["watch"] is not None, None
        spans.note("views", action="unwatch")
        return watching

    def unpin(self, name=None):
        """Let go of the view pinned as `name` (all pinned views without one)."""
        spans.note("views", action="unpin", **({"pin": str(name)} if name is not None else {}))

    def drain(self):
        """What the unit that calls this produced, for its result (the kernel calls it at a
        program's end, runtime/execution/kernel.py): its attachments, events and views (then
        cleared), the state, model usage, and the enabled skills' turn report."""
        box, own = self._box(), self._entries.root.box
        if box is not own:
            # What the model's own rules and handlers gathered outside every unit comes
            # with the next program's result.
            box.attachments[:0], box.events[:0], box.looks[:0] = own.attachments, own.events, own.looks
            for kind, count in own.event_counts.items():
                box.event_counts[kind] = box.event_counts.get(kind, 0) + count
            own.attachments, own.events, own.looks, own.event_counts = [], [], [], {}
        watch = self._views["watch"]
        if watch is not None and not self.state.get("ended"):
            # A standing watch: the views the program did not look at itself.
            looked = {item["camera"] for item in self._looks if not item.get("region")}
            due = [name for name in watch["cameras"] if name not in looked]
            if due:
                try:
                    self.look(due)
                except Exception as error:
                    spans.note("cleanup_error", message=f"watch: {type(error).__name__}: {error}")
        report = self._turn_report()
        data = {"attachments": self._attachments, "events": self._events,
                "state": self.state, "usage": self._drain_usage()}
        if self._event_counts:
            data["event_counts"] = self._event_counts
            self._event_counts = {}
        if report is not None:
            data["report"] = report
        self._attachments, self._events = [], []
        if self._looks:
            data["looks"], self._looks = self._looks, []
        for name, other in list(self._attached.items()):
            # An attached environment's part of the cell: its state and executions under
            # its name, its pictures with the conversation's own.
            try:
                part = other.drain()
            except Exception as error:
                part = {"state": {}, "events": [], "attachments": [],
                        "error": f"{type(error).__name__}: {error}"}
            data["attachments"] = data["attachments"] + [
                {**item, "caption": f"{name}: {item.get('caption') or ''}".rstrip(": ")}
                for item in part.pop("attachments", [])]
            for key, usage in (part.pop("usage", None) or {}).items():
                data["usage"].setdefault(key, usage)
            if part.get("looks"):
                data["looks"] = data.get("looks", []) + [{**item, "camera": f"{name}.{item['camera']}"}
                                                          for item in part.pop("looks")]
            data.setdefault("environments", {})[name] = {
                key: value for key, value in part.items() if key in ("state", "events", "event_counts", "error")}
        return data

    def attach(self, name, given):
        """Take another environment into this session under `name`: its session beside this
        one (runtime/execution/attached.py), its calls in the namespace as name.call(...)."""
        from harness.runtime.execution.attached import Attached, build

        if name in self._attached:
            return self.namespace[name]
        if name in self.namespace:
            raise ValueError(f"{name} is a name of this conversation's own; it cannot be an environment's")
        session = build(name, given)
        self._attached[name] = session
        proxy = self.namespace[name] = self._api_changes[name] = Attached(name, session)
        return proxy

    def detach(self, name):
        """Give an attached environment back: its session closed, its name gone."""
        session = self._attached.pop(name, None)
        if session is None:
            return False
        proxy = self.namespace.pop(name, None)
        if proxy is not None:
            object.__setattr__(proxy, "_live", False)
        self._api_changes[name] = None
        try:
            session.close()
        except Exception as error:
            spans.note("cleanup_error", message=f"{name}: {type(error).__name__}: {error}")
        return True

    def load_skills(self, names):
        """Switch skills on while the conversation runs (sub-agents the user agreed to): their
        exports join the namespace."""
        from harness.runtime.execution.skills import namespace, reporters

        new = [name for name in names if name not in self.skills]
        if not new:
            return []
        added = namespace(self, new)
        self.skills = [*self.skills, *new]
        self.namespace.update(added)
        self._api_changes.update(added)
        self._reporters = reporters(self.skills)
        return sorted(name for name in added if not name.startswith("_"))

    def _turn_report(self):
        """What the enabled skills add to the model's next turn after every program (each
        skill's turn_report: text, and camera images to show in place of the plain ones),
        joined; None when none adds anything or the episode has ended. A report that fails
        becomes a note, never a failed program."""
        if self.state.get("ended"):
            return None
        texts, images = [], {}
        for report in getattr(self, "_reporters", ()):
            try:
                part = report(self)
            except Exception as error:
                texts.append(f"({report.__module__} could not report this turn: {type(error).__name__}: {error})")
                continue
            if part:
                if part.get("text"):
                    texts.append(part["text"])
                images.update(part.get("images") or {})
        if not texts and not images:
            return None
        return {"text": "\n".join(texts), "images": images}

    def close(self):
        """End the model's units, stop the tick and close the worker connection."""
        for name in list(self.__dict__.get("_attached", {})):
            self.detach(name)
        self._entries.close()
        ticker = self.__dict__.get("_tick_loop")
        if ticker is not None:
            ticker.stop()
        try:
            for name, close in self.__dict__.pop("_policy_closers", {}).items():
                try:
                    close()
                except Exception as error:
                    spans.note("policy_cleanup_error", policy=name, error=str(error))
        finally:
            self.env.close()

    def _drain_usage(self):
        """Model usage of the perception and verifier calls since the last drain."""
        usage = {}
        for name, model in (("vision", self.vision), ("pointer", self.pointer), ("verifier", self.verifier)):
            if model is not None and model.usage["calls"]:
                usage[name] = dict(model.usage)
                model.usage.update(calls=0, **USAGE)
        return usage

    def _vision(self):
        if self.vision is None:
            raise RuntimeError("No vision model is configured for this harness (the vlm role, with the "
                               "perception package)")
        return self.vision

    def _execute(self, skill, parameters, *args, **kwargs):
        """One bounded execution (_bounded), recorded as a span of the skill lane with the
        event it ended with (core/spans.py)."""
        with spans.span("skill", skill, parameters=parameters, tick=self.state.get("step")) as end:
            try:
                trace = self._bounded(skill, parameters, *args, **kwargs)
            except (Escalation, EpisodeEnded) as stopped:
                end.update(event_kind=stopped.trace.event.kind, end_tick=stopped.trace.end_tick, escalated=True,
                           **_reason(stopped.trace.event))
                raise
            end.update(event_kind=trace.event.kind, end_tick=trace.end_tick, **_reason(trace.event))
            return trace

    def _bounded(self, skill, parameters, command_fn, max_seconds, region, until, timeout_is_nominal=False,
                 cameras_at=None):
        """One bounded execution: command_fn(state, tick) gives each step's command (None
        when the skill is done, or an Event that ends it), for at most `max_seconds`,
        inside `region` (the embodiment's scope), until `until(view)` holds. It runs on the
        tick as a program entry (_steps) and returns its trace once that ended."""
        max_seconds = self.default_max_seconds if max_seconds is None else float(max_seconds)

        def steps():
            # (Made anew each time the harness starts the execution again: runtime/tick.py.)
            return self._steps(skill, parameters, command_fn, max_seconds, region, until, timeout_is_nominal,
                               cameras_at)

        result = Execution(session=self, skill=skill, parameters=parameters, steps=steps)
        trace = result.detail.get("trace")
        if trace is None:
            # Not confirmed: the run does not let it act now.
            step = self.state["step"]
            trace = ExecutionTrace(skill, parameters, step, step, Event(
                ev.SKILL_ERROR, skill, {"reason": result.reason, **result.detail}, step))
        return self._finish(trace)

    def _refuses(self, skill):
        """Why the run does not let the execution `skill` act now ({"reason", "hint"}), or
        None (Execution.confirm). The skeleton refuses nothing; an embodiment may (a robot's
        learned policy)."""
        return None

    def _steps(self, skill, parameters, command_fn, max_seconds, region, until, timeout_is_nominal, cameras_at):
        """The program entry of a bounded execution (runtime/tick.py): every step it
        observes, runs the guards and the termination conditions, and yields the command
        to send with the cameras whose images the reply should carry; it receives the
        worker's reply to the step the tick sent, and returns the execution's trace."""
        # Its time is the environment's steps where each step is a fixed time of it (a
        # simulation), else the wall's (runtime/tick.py driving).
        step_seconds = self._ticker.step_seconds
        max_ticks = max(1, math.ceil(max_seconds / step_seconds)) if step_seconds else None
        over = ev.COMPLETED if timeout_is_nominal else ev.TIMEOUT
        start = self.state["step"]
        samples = []
        receipt = None
        value = None
        deadline = time.monotonic() + max_seconds
        tick = 0
        event = None

        def check(predicate=None):
            state = self.state
            if control.pause_requested():
                return Event(ev.USER_PAUSED, "user", tick=state["step"])
            if max_ticks is None and time.monotonic() >= deadline:
                return Event(over, skill, {"max_seconds": max_seconds}, state["step"])
            view = self._view(state, tick)
            if cameras_at is not None:
                view["observation"] = self._live
            try:
                guard = self.reactive.evaluate(view)
                if guard is not None or predicate is None:
                    return guard
                if call_reactive("until", predicate, view, budget_seconds=self.reactive.budget_seconds):
                    return Event(ev.PREDICATE_SATISFIED, "until", tick=state["step"])
            except ReactiveFault as fault:
                return fault

        stop = None
        self._motion_started(self.state)
        while event is None:
            state = self.state
            if state.get("ended"):
                # The worker ended the episode between steps (a wall clock's observation saw
                # it: a practice segment's goal or time limit): nothing more is sent.
                self._motion_stopped(state)
                raise EpisodeEnded(ExecutionTrace(skill, parameters, start, state["step"],
                                                  Event(ev.EPISODE_ENDED, "environment", tick=state["step"]),
                                                  samples))
            if control.pause_requested():
                self._motion_stopped(state)
                event = Event(ev.USER_PAUSED, "user", tick=state["step"])
                break
            outcome, observed = stop or (check(until), state)
            if outcome is not None:
                if isinstance(outcome, Event):
                    event = outcome
                    break
                self._motion_stopped(observed)
                if isinstance(outcome, ReactiveFault):
                    command = self._base_command(observed)
                else:
                    # What the unit whose execution ends holds down goes up; the other
                    # units' holds stay (the rule may be the model's, watching them all).
                    self._let_go_under(self._entries.current().id)
                    command = self._guard_command(outcome.action, observed) if (
                        outcome.action in self.guard_actions and outcome.action != STOP) else None
                try:
                    held = (yield command, None) if command is not None else None
                except Preempted:
                    held = None
                if self.state.get("ended"):
                    continue
                event = self._rule_event(outcome, observed, held)
                break
            if region is not None and self._outside(region, state):
                event = Event(ev.REGION_EXIT, skill, {"region": region}, state["step"])
                break
            if max_ticks is not None and tick >= max_ticks:
                event = Event(over, skill, {"max_seconds": max_seconds}, state["step"])
                break
            try:
                target = command_fn(state, tick)
            except ReactiveFault as fault:
                target = self._rule_event(fault, state)
            if target is None or isinstance(target, Event):
                event = target if target is not None else Event(ev.COMPLETED, skill, receipt or {}, state["step"])
                break
            try:
                result = yield target, (cameras_at(tick) if cameras_at else None), check
            except Preempted as taken:
                # A unit of higher priority takes the embodiment: this execution ends here.
                self._motion_stopped(self.state)
                event = Event(ev.PREEMPTED, skill, {"by": taken.by, "priority": taken.priority}, self.state["step"])
                break
            if result is None and self.state.get("ended"):
                continue
            if isinstance(result, tuple):
                stop = result
                continue
            if event := ev.input_refusal(result, result["state"]["step"]):
                if "action_id" in result:
                    event.detail["action_id"] = result["action_id"]
                break
            if "action_id" in result:
                receipt = {"action_id": result["action_id"]}
                if delivery := result.get("delivery"):
                    receipt["delivery_status"] = delivery.get("status")
                if "evidence" in result:
                    receipt["evidence"] = result["evidence"]
            value = result.get("result")
            self._motion_ticked(result["shield"]["command"])
            if tick % 5 == 0:
                samples.append(self._sample(self.state))
            tick += 1
            if self.state["ended"]:
                trace = ExecutionTrace(skill, parameters, start, self.state["step"],
                                       Event(ev.EPISODE_ENDED, "environment", tick=self.state["step"]),
                                       samples)
                raise EpisodeEnded(trace)
        self._motion_stopped(self.state, arrived=event.kind == ev.COMPLETED)
        return ExecutionTrace(skill, parameters, start, self.state["step"], event, samples, result=value)

    @property
    def _entries(self):
        """The session's tree of entries (runtime/execution/entries.py), made on first use."""
        tree = self.__dict__.get("_entry_tree")
        if tree is None:
            tree = self.__dict__["_entry_tree"] = Tree(self)
        return tree

    @property
    def _ticker(self):
        """The session's tick (runtime/tick.py), made on first use."""
        ticker = self.__dict__.get("_tick_loop")
        if ticker is None:
            ticker = self.__dict__["_tick_loop"] = self._new_tick()
        return ticker

    def _new_tick(self):
        return Tick(self)

    def _finish(self, trace):
        tree = self._entries
        entry = tree.current()
        handled_here = not trace.ok and trace.event.kind != ev.USER_PAUSED
        record = tree.record_event(trace, entry if handled_here and entry is not tree.root else None)
        if trace.ok:
            return trace
        if not handled_here or not tree.handle(entry, trace):
            raise Escalation(trace)
        record["handled"] = True
        return trace

    def _failed(self, skill, parameters, reason):
        step = self.state["step"]
        return ExecutionTrace(skill, parameters, step, step, Event(ev.SKILL_ERROR, skill, {"reason": reason}, step))

    def guide(self, name) -> str:
        """A page of instructions, read on demand (GUIDES): "tree" (how a tree of reflexes is
        designed and set, and every setting of a node), "units" (how units run and share the
        environment). The host gives a page that was read again after a summary of the
        conversation. Reading "tree" comes before the first node: set_reflex is refused
        until then."""
        if name not in GUIDES:
            raise ValueError(f"guide(name): name is one of {sorted(GUIDES)}, got {name!r}")
        if name == "tree":
            self._method_read = True
        spans.note("guide", name=name)
        return GUIDES[name].read_text(encoding="utf-8")

    def reflex_method(self) -> str:
        """guide("tree"), under its earlier name."""
        return self.guide("tree")

    def _try_reflex(self, node, test) -> dict:
        """Run the trial of a node that is in the tree: `test` brings its situation about,
        and the node is watched: whether it had its turn, how long that took from the
        trial's start, and for a node with a program whether that left the situation over
        (its condition, which says when the situation is there, no longer held)."""
        began, did, did_not, started, error = node.triggered, node.did, node.did_not, time.monotonic(), None
        ticker = self.__dict__.get("_tick_loop")

        def look():
            # (The environment is read so that the tree is judged on what the trial did.)
            try:
                self._observe()
                if ticker is not None:
                    ticker.judge()
            except Exception:
                pass
            time.sleep(0.1)

        node.trying = True
        try:
            try:
                test()
            except Exception as raised:
                # (What the trial did may have been ended by the node itself: that is its turn.)
                error = f"{type(raised).__name__}: {raised}"[:300]
            deadline = time.monotonic() + TRIAL_SECONDS
            while node.triggered == began and time.monotonic() < deadline:
                look()
            turn = node.triggered > began
            seconds = round(time.monotonic() - started, 2)
            done = None
            if not turn and node.fault:
                # (Why it had no turn: its condition could not be judged.)
                error = node.fault[:300]
            if turn and node.do is not None:
                deadline = time.monotonic() + 3 * TRIAL_SECONDS
                # (Its program has ended when the tree has counted it as done or not done.)
                while node.did == did and node.did_not == did_not and time.monotonic() < deadline:
                    look()
                done = node.did > did
        finally:
            node.trying = False
        shown = {"tried": True, "turn": turn, **({"seconds": seconds} if turn else {}),
                 **({"done": done} if node.do is not None and turn else {}),
                 **({"error": error} if error and not turn else {})}
        node.trial = shown
        self.reactive._touched()
        return {**shown, **({"last": node.last} if node.do is not None and turn and node.last is not None else {})}

    def set_reflex(self, name, when, do=None, *, under=None, priority=0, every=None, again_seconds=0.0,
                   ends=False, tell=None, tell_failed="now", test=None):
        """Put the node `name` into the tree of reflexes (runtime/reactive/tree.py), in place
        of a node of that name. `when`: a function of the view (the node has its turn while
        it holds: the situation it answers), or the name of an event (it answers that
        event). `do`: a program (a function, started as a unit; its work is done when the
        situation is over), the name of an event to raise, an action of the environment that
        ends what runs ("stop"), or None: then only the nodes set `under`
        it answer. `under`: the node it is a narrower situation of (any node whose `when` is
        a condition, whatever that node does itself). `priority`: its own (the higher first,
        0 or more; what a program's at_priority is compared with). `every`: the seconds
        between judgements of its condition (None: when the state or the facts change). `again_seconds`: before it may begin again. Its name."""
        # (What a library entry sets when a session starts was tried when it was admitted.)
        staged = getattr(_staging, "layers", None) is not None
        if self._method_required and not staged:
            if not self._method_read:
                raise ValueError(METHOD_FIRST)
            if do is None:
                raise ValueError(ACTION_NEEDED)
            self._condition_judges(name, when, under)
        if test is not None and not callable(test):
            raise TypeError(TRIAL_IS_A_FUNCTION)
        found = self.reactive.set(name, when, do, under=under, priority=priority, every=every,
                                  again_seconds=again_seconds, ends=ends, tell=tell, tell_failed=tell_failed)
        if staged or test is None:
            return found
        return {"name": name, **self._try_reflex(self.reactive.nodes[name], test)}

    def _condition_judges(self, name, when, under) -> None:
        """Refuse a node whose condition raises on the state as it is now: a tree that cannot
        run is not set. A node under others is judged as the tree would judge it: only while
        the conditions above it hold."""
        if not callable(when) or self.reactive.view is None:
            return
        try:
            view = self.reactive.view()
        except Exception:
            return
        above = self.reactive.nodes.get(under) if under is not None else None
        if above is not None and not (self.reactive._above_hold(above, view) and self.reactive._run(above, view)):
            return
        try:
            call_reactive(name, when, view, budget_seconds=1.0)
        except ReactiveFault as fault:
            raise ValueError(CONDITION_FAILS.format(reason=fault.reason)) from None

    @property
    def pauses(self) -> bool:
        """Whether the environment pauses a call for a unit of higher priority and lets it
        go on afterwards (its profile says "pauses"); else that call ends with PREEMPTED."""
        return bool(self.profile.get("pauses"))

    def _pause_execution(self, by=None):
        """Have the environment hold what the call that runs is doing, for the unit `by`
        (a reflex's name, or the unit's); what it answers is given back to it when that
        call goes on."""
        return self.env.call("pause", episode_id=self.episode_id, by=by)

    def _resume_execution(self, held):
        self.env.call("resume", episode_id=self.episode_id, held=held)
        self._observe()

    def at_priority(self, priority):
        """`with at_priority(priority):` the program holds the environment with `priority`
        for the block: for one action that must not be broken off, not for a stage. A
        reflex whose place is `priority` or above takes it from the program as before. One
        below does not act during the block: it is judged again when the block ends and
        acts if its condition still holds, and the model is told once that it was held
        back. What still ends the program: cancelling it, the time of its calls, a reflex
        that ends what runs, the end of the episode."""
        return self._entries.at_priority(priority)

    def run_controller(self, fn, until=None, max_seconds=None):
        """Run `fn(view)` for each step, until it returns None or a stopping condition holds."""
        def command(state, tick):
            return call_reactive("controller", fn, self._view(state, tick),
                                 budget_seconds=self.reactive.budget_seconds)

        return self._execute("run_controller", {}, command, max_seconds, None, until)

    def _let_go_under(self, owner):
        """A rule ended what the unit `owner` does: with channels, the keys and buttons it
        holds down (key_down) go up at the next period (None: every unit's)."""
        tick = self.__dict__.get("_tick_loop")
        if tick is None or not tick.channels:
            return
        tree = self._entries
        tick.let_go(tree.under(tree.get(owner) if owner is not None else tree.root))

    def _rule_event(self, guard, state, held=None):
        detail = {"hold_rejected": held["shield"]["reasons"]} if held is not None and not held["executed"] else {}
        if isinstance(guard, ReactiveFault):
            return fault_event(guard, state.get("step"), **detail)
        detail = {"guard": guard.describe(), **detail}
        # Counted per episode (summary guard_triggers) and tallied by practice.
        spans.note("guard", name=guard.name, action=guard.action, stops=guard.stops)
        if guard.action in self.guard_actions:
            return Event(ev.GUARD_TRIGGERED, guard.name, {**detail, "action": guard.action}, state["step"])
        return Event(guard.action, guard.name, detail, state["step"])

    def _guard_command(self, action, state):
        """The command a guard action other than stop sends: hold keeps everything as it
        is."""
        return self._base_command(state)

    # What the embodiment's session defines.

    def _base_command(self, state):
        """The command that leaves everything as it is."""
        raise NotImplementedError

    def _tick(self, command, cameras=None):
        """Send one step's command to the worker; the worker's reply {"executed",
        "shield", "state", ...}, with self.state updated."""
        raise NotImplementedError

    def _motion_started(self, state):
        """An execution begins (what an embodiment holds afterwards may depend on it)."""

    def _motion_ticked(self, command):
        """The shield passed this command of the running execution."""

    def _motion_stopped(self, state, arrived=False):
        """The running execution was interrupted (a guard, a fault) or ended; `arrived`
        when it completed."""

    def _take_observation_events(self, state):
        """An embodiment's new observation events, offered once to existing handlers."""
        return ()

    def _reactive_view(self, state, tick):
        """What guards, controllers and until predicates observe at this step."""
        raise NotImplementedError

    # With channels (runtime/tick.py).

    def _plan(self, command):
        """A command taken apart: (the channels it drives, its periods' parts, a change of
        what its entry holds down or None); raises tick.Refused for one it cannot take."""
        raise NotImplementedError

    def _merge(self, parts, idle):
        """One period's command from the parts of the executions and holds, with the
        channels of `idle` at their default."""
        raise NotImplementedError

    def _still(self, last):
        """The command that keeps what the last sent command (None: none yet) held."""
        raise NotImplementedError

    def _admit(self, command, commit=False):
        """The shield's verdict on a merged command, judged here before it is sent;
        `commit` once the worker executed it."""
        raise NotImplementedError

    def _channels_of(self, part) -> set:
        """The channels a part uses."""
        raise NotImplementedError

    def _channel_of_reason(self, reason):
        """The channel a shield's reason is about, when it names an input and not the
        channel."""
        return None

    def _observe(self):
        """Refresh the state from the worker (between two ticks the world may have moved
        on): for a rule on time, and at each period of an environment driven at a rate."""
        self.state = self.env.call("state", episode_id=self.episode_id)

    def _outside(self, region, state):
        """Whether the state has left an execution's scope."""
        raise NotImplementedError

    def _sample(self, state):
        """What a trace keeps of a step (every fifth)."""
        return {"step": state["step"]}


class Facts:
    """What the run knows, shared: named values that its programs read and write and its
    rule conditions read (the view's "facts"). A program that was ended and started again
    goes on from them. Values are plain data (what JSON holds); a change is a `fact`
    record, and the rules that read facts are judged."""

    LIMIT = 20000

    def __init__(self, changed=None, values=None):
        # (`values`: the facts an earlier process of the conversation kept.)
        self._values, self._lock, self._changed = dict(values or {}), threading.Lock(), changed
        self.version = 0

    def set(self, name, value):
        """Set the fact `name` to `value`; returns the value."""
        if not isinstance(name, str) or not name:
            raise ValueError("a fact's name is a nonempty string")
        try:
            text = json.dumps(value)
        except (TypeError, ValueError):
            raise ValueError("a fact's value is plain data: numbers, text, true/false, None, lists and dicts") from None
        if len(text) > self.LIMIT:
            raise ValueError(f"a fact holds at most {self.LIMIT} characters of data; keep large data elsewhere")
        with self._lock:
            self._values[name] = json.loads(text)
            self.version += 1
        # (`data`: the whole value, for the conversation that keeps the facts; not recorded.)
        spans.note("fact", name=name, value=text[:300], data=text)
        if self._changed is not None:
            self._changed()
        return value

    def get(self, name, default=None):
        """The fact `name`, or `default`."""
        with self._lock:
            return self._values.get(name, default)

    def drop(self, name):
        """Forget the fact `name`; whether it was there."""
        with self._lock:
            there = self._values.pop(name, self) is not self
            self.version += there
        if there:
            spans.note("fact", name=name, dropped=True)
            if self._changed is not None:
                self._changed()
        return there

    def view(self) -> dict:
        """The facts as they are now, as a dict of their own."""
        with self._lock:
            return dict(self._values)

    __getitem__ = lambda self, name: self.view()[name]  # noqa: E731
    __setitem__ = set

    def __contains__(self, name):
        return name in self.view()

    def __repr__(self):
        return f"facts({self.view()!r})"


class Looked:
    """What look() saw: .state, .cameras, and the pictures show() takes (a crop of one is
    look(region=...))."""

    def __init__(self, state, urls):
        self.state, self._urls = state, dict(urls)
        self.cameras = list(urls)

    def __repr__(self):
        return f"Looked({', '.join(self.cameras) or 'nothing'}): it comes with this program's result"


def _cropped(url, region, fmt):
    """The part `region` (x, y, width, height) of the image at data URL `url`, as a data URL."""
    from harness.core.codec import decode_data_url, image_data_url

    try:
        import numpy as np
    except ImportError:
        raise RuntimeError("look(region=...) needs NumPy in this kernel; look without region, or read the "
                           "structure (elements(), read_page())") from None
    raw = decode_data_url(url)
    try:
        import cv2

        image = cv2.cvtColor(cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB)
    except ImportError:
        import io

        from PIL import Image

        image = np.asarray(Image.open(io.BytesIO(raw)).convert("RGB"))
    x, y, width, height = region
    part = image[max(y, 0):y + height, max(x, 0):x + width]
    if part.size == 0:
        raise ValueError(f"region {region} is outside the view ({image.shape[1]} x {image.shape[0]})")
    return image_data_url(part, fmt)


class Execution(ClosedLoop):
    """A bounded execution as a closed loop: confirm the run lets it act (_refuses), do its
    steps on the tick, check it ended nominally. One try (a motion that may have run is never
    silently retried); every exception ends the program; its span is its record. The trace
    is the Result's detail["trace"] (none when not confirmed: then the reason and hint)."""

    tries = 1
    max_seconds = math.inf
    catches = ()

    def confirm(self):
        refused = self.session._refuses(self.skill)
        if refused is None:
            return True
        self.detail["hint"] = refused.get("hint")
        return refused["reason"]

    def do(self):
        self.detail["trace"] = self.session._ticker.run(self.steps)

    def check(self):
        trace = self.detail["trace"]
        return True if trace.ok else f"{trace.event.kind} from {trace.event.source}"

    def report(self, number, what, ok, seconds, reason):
        pass


_SESSION_CLASSES = {}


def _import(spec: str):
    module, _, attribute = spec.partition(":")
    return getattr(importlib.import_module(module), attribute)


def _reason(event) -> dict:
    """The reason an execution's event gives, for its span (practice tallies failures by it)."""
    reason = (event.detail or {}).get("reason") if isinstance(event.detail, dict) else None
    return {"reason": str(reason)[:120]} if reason and event.kind not in ev.NOMINAL else {}


def image_role(config: dict | None, role: str):
    """A model role that answers about images (vlm, pointer, verifier): an instance of the
    class its config names ([class] "module:Class", a package's: config/agent.py
    image_roles), or None without a config or a class."""
    module, _, name = str((config or {}).get("class") or "").partition(":")
    if not module or not name:
        return None
    return getattr(importlib.import_module(module), name)(
        {key: value for key, value in config.items() if key != "class"}, role=role)


def service_client(config: dict):
    """The client of a service the episode's programs use (a segmenter, a vision service): the
    class its manifest names ([client] class, "module:Class"), given its url, timeout and
    on-demand start."""
    import importlib

    module, _, name = str(config.get("class") or "").partition(":")
    if not module or not name:
        raise ValueError(f"the service at {config.get('url')} names no client class ([client] class)")
    return getattr(importlib.import_module(module), name)(
        config["url"], timeout=float(config.get("timeout_seconds", 120.0)), on_demand=config.get("on_demand"))


def session_class(embodiment: str = "none", knowledge: str | None = None):
    """The session of an embodiment kind with the mixin of every skill for that kind (the
    skills enabled for a run only decide the namespace; a skill's methods may use
    another's); with knowledge "learned" (a game the agent learns itself), without the
    skills written for a game by hand, whose modules are then never imported."""
    knowledge = knowledge or KINDS[embodiment].knowledge or "handwritten"
    key = (embodiment, knowledge)
    if key not in _SESSION_CLASSES:
        from harness.runtime.execution.skills import mixins

        if embodiment not in SESSIONS:
            raise ValueError(f"No session for the embodiment kind {embodiment!r}; sessions exist for "
                             f"{sorted(SESSIONS)}")
        base = _import(SESSIONS[embodiment])
        _SESSION_CLASSES[key] = type("Session", (*mixins(embodiment=embodiment, knowledge=knowledge), base),
                                     {"__module__": base.__module__, "embodiment": embodiment,
                                      "knowledge": knowledge})
    return _SESSION_CLASSES[key]


def create_session(options):
    """Kernel bootstrap: the session of options["embodiment"] (default: none, no environment)."""
    return session_class(options.get("embodiment", "none"), options.get("knowledge"))(options)
