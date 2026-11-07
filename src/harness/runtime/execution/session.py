"""The episode core: the session skeleton every embodiment's kernel session is.

A kernel session connects to a worker, keeps the state it reports, the model clients of the
skills (VLM, pointer, verifier, segmenter) and the episode's events, and runs bounded
executions as program entries on its always-on tick (runtime/tick.py): at each step the
reactive layer's rules that stop are asked, the termination conditions are checked, and one
command goes to the worker, whose shield passes or rejects it. An execution ends with an
event; one that is not nominal goes to the rules that answer it (on()), up the tree of
entries (runtime/execution/entries.py), and one nobody answers escalates to the model.

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
import math
import time

from harness.core import spans
from harness.core.remote import RemoteEnvironment
from harness.embodiments import KINDS
from harness.runtime.events import EpisodeEnded, Escalation, Event, ExecutionTrace
from harness.runtime.execution import control
from harness.runtime import events as ev
from harness.runtime.decision.model import USAGE
from harness.runtime.execution.entries import ClosedLoop, Tree
from harness.runtime.reactive.rules import HOLD, RAISES, STOP, ReactiveFault, ReactiveLayer, call_reactive, fault_event
from harness.runtime.tick import Tick, delay_ticks


# The session of each embodiment kind, as "module:Class" (embodiments.KINDS).
SESSIONS = {name: kind.session for name, kind in KINDS.items()}


class EpisodeCore:
    """The session skeleton every embodiment and skill builds on: the worker connection and
    profile, the state, the model clients, the reactive layer (guards, reflexes, answers to
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
        self.reactive = ReactiveLayer(float(options.get("reactive_budget_ms", 5.0)) / 1000.0, self.guard_actions)
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
        self._attachments = []
        self._events = []
        self._event_counts = {}
        # What runs at the same time (runtime/execution/entries.py); a guard belongs to the entry that
        # set it.
        self._entry_tree = Tree(self)
        self.reactive.owner = lambda: self._entries.current().id
        # The guards a wall clock's idle tick saw firing (each is an event once: reactive.apply).
        self._idle_fired = set()
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
            "rule": self.rule, "when": self.reactive.when, "watch": self.reactive.watch,
            "on": self.reactive.on, "clear_rules": self.reactive.clear,
            "run_controller": self.run_controller,
        }
        self._reporters = reporters(self.skills)
        self._embodiment_ready(options)
        self.reactive.wake_observer = self._ticker._wake
        self._ticker.start()

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

    def drain(self):
        """What the last cell produced, for the kernel's reply: attachments and events
        gathered since the previous drain (then cleared), the state, model usage, and the
        enabled skills' turn report."""
        report = self._turn_report()
        data = {"attachments": self._attachments, "events": self._events,
                "state": self.state, "usage": self._drain_usage()}
        if self._event_counts:
            data["event_counts"] = self._event_counts
            self._event_counts = {}
        if report is not None:
            data["report"] = report
        entries = self._entries.drain()
        if entries:
            data["entries"] = entries
        self._attachments, self._events = [], []
        return data

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
        """Cancel the entries, stop the tick and close the worker connection."""
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
        steps = self._steps(skill, parameters, command_fn, max_seconds, region, until, timeout_is_nominal,
                            cameras_at)
        result = Execution(session=self, skill=skill, parameters=parameters, steps=steps)
        trace = result.detail.get("trace")
        if trace is None:
            # Not confirmed: the run does not let it act now.
            steps.close()
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
        max_ticks = max(1, math.ceil(max_seconds * self.hz))
        # The guards of the entry that runs it and of those above it watch it.
        scope = {entry.id for entry in self._entries.current().lineage()}
        start = self.state["step"]
        samples = []
        receipt = None
        value = None
        deadline = time.monotonic() + max_seconds
        discrete = self.profile.get("clock") == "events"
        tick = 0
        event = None

        def check(predicate=None):
            state = self.state
            if control.pause_requested():
                return Event(ev.USER_PAUSED, "user", tick=state["step"])
            if discrete and time.monotonic() >= deadline:
                return Event(ev.TIMEOUT, skill, {"max_seconds": max_seconds}, state["step"])
            view = self._reactive_view(state, tick)
            if cameras_at is not None:
                view["observation"] = self._live
            try:
                guard = self.reactive.evaluate(view, scope)
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
            paused = control.pause_requested()
            if paused or control.message_arrived() and self._entries.current() is self._entries.root:
                self._motion_stopped(state)
                event = Event(ev.USER_PAUSED if paused else ev.USER_MESSAGE, "user", tick=state["step"])
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
                    self._idle_fired.add(outcome.name)
                    self._let_go_under(outcome.owner)
                    command = self._guard_command(outcome.action, observed) if (
                        outcome.action in self.guard_actions and outcome.action != STOP) else None
                held = (yield command, None) if command is not None else None
                if self.state.get("ended"):
                    continue
                event = self._rule_event(outcome, observed, held)
                break
            if region is not None and self._outside(region, state):
                event = Event(ev.REGION_EXIT, skill, {"region": region}, state["step"])
                break
            if not discrete and tick >= max_ticks:
                kind = ev.COMPLETED if timeout_is_nominal else ev.TIMEOUT
                event = Event(kind, skill, {"max_seconds": max_seconds}, state["step"])
                break
            try:
                target = command_fn(state, tick)
            except ReactiveFault as fault:
                target = self._rule_event(fault, state)
            if target is None or isinstance(target, Event):
                event = target if target is not None else Event(ev.COMPLETED, skill, receipt or {}, state["step"])
                break
            result = yield target, (cameras_at(tick) if cameras_at else None), check
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
        handled_here = not trace.ok and trace.event.kind not in (ev.USER_PAUSED, ev.USER_MESSAGE)
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

    def rule(self, decide, name=None, priority=0):
        """Register an observation rule that can raise an event or stop an entry in scope."""
        return self.reactive.rule(decide, RAISES, name, priority).name

    def run_controller(self, fn, until=None, max_seconds=None):
        """Run `fn(view)` for each step, until it returns None or a stopping condition holds."""
        def command(state, tick):
            return call_reactive("controller", fn, self._reactive_view(state, tick),
                                 budget_seconds=self.reactive.budget_seconds)

        return self._execute("run_controller", {}, command, max_seconds, None, until)

    def reflex(self, control, priority="survival", name=None):
        """Run `control(view)` on the tick every control period from now on, as a rule of
        this entry that acts (runtime/reactive/rules.py): it returns None or the period's act ({"keys",
        "buttons", "dx", "dy", "take"}) and wins the channels it needs over lower
        priorities and over what the entries do. Its name."""
        if not self.channels:
            raise ValueError("reflexes run on an embodiment with channels (a game's)")
        name = name or getattr(control, "__name__", None) or type(control).__name__
        self.reactive.reflex(name, control, priority)
        self._ticker.start()
        return name

    def _let_go_under(self, owner):
        """A guard that stops fired: with channels, the keys and buttons that the entry
        `owner` and the entries below it hold down (key_down) go up at the next period, as
        a stop of all they do (None: every entry's)."""
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
        spans.note("guard", name=guard.name, action=guard.action, stops=guard.does == "stop")
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
        """Refresh the state at the start of a tick of a wall-clock embodiment (between
        two ticks the world moved on); a steps clock's last reply is the state."""
        self.state = self.env.call("state", episode_id=self.episode_id)

    def _outside(self, region, state):
        """Whether the state has left an execution's scope."""
        raise NotImplementedError

    def _sample(self, state):
        """What a trace keeps of a step (every fifth)."""
        return {"step": state["step"]}


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


def session_class(embodiment: str = "robot", knowledge: str | None = None):
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
    """Kernel bootstrap: the session of options["embodiment"] (default robot)."""
    return session_class(options.get("embodiment", "robot"), options.get("knowledge"))(options)
