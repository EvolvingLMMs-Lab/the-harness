"""Other environments of one conversation, and its sub-agents on request (host side).

A conversation works in the environment its user chose. A program may ask for another
kind (skills/environments: use_environment); the request reaches the conversation as a
note, and this module decides and does it:

  permission   the user's setting environments.attach and its rules by kind: never,
               ask_each, ask_once_session (the default: once per conversation and kind),
               allow. A user who chose to skip confirmations (their physical-input level
               is `allow`, in the settings or for this run) is not asked; a `never` level
               still refuses. Where nobody can be asked (a run without a user) and the
               level asks, the request is refused with the reason: it never waits and is
               never allowed silently.
  the place    the session host's (Place): a workspace of that kind from the same pools,
               under the same limits as conversations and sub-agents, until release or
               the conversation's end.
  the session  the kernel builds the kind's session beside its own (runtime/execution/
               attached.py); every call of it comes back here as a worker request, so the
               host's checks and the user's approvals apply as they do to the
               conversation's own worker. The kind's own prompt sections join the system
               prompt while it is attached.

Every attachment, its reason and how it was allowed is a record of the trace
(environment_attached, environment_refused, environment_released) and a span of the
timeline, asked or not.

Sub-agents are off unless the user switched them on (settings, the conversation's start
or while it runs); request_agents asks the user, and a yes loads their calls and prompt.
"""

import threading

from harness.embodiments import KINDS, embodiment_kind

LEVELS = ("never", "ask_each", "ask_once_session", "allow")


class Refused(ValueError):
    """Why an environment was not attached; the program gets it as the call's error."""


class Place:
    """What a server gives a conversation that asks for another environment. This one
    gives none (a conversation run in a process of its own)."""

    def kinds(self) -> dict:
        """{kind: {"label", "about", optionally "folder"}} of what may be attached."""
        return {}

    def level(self, kind, runtime) -> tuple:
        """(the level of LEVELS for `kind`, whether the user skips confirmations)."""
        return "never", False

    def begin(self, conversation, kind, folder, cancelled) -> dict:
        """Take a workspace of `kind`: {"env" (its worker, with the host's key), "embodiment",
        "task", "skills" (its session's), "prompt" (its own sections), "release" (give it
        back), optionally "metadata"}."""
        raise Refused(f"this conversation has no place to take {kind} from")

    def agents(self) -> dict:
        """{"mode": off or on (the setting), "depth": how deep sub-agents may go}."""
        return {"mode": "off", "depth": 0}


class Environments:
    """The environments attached to one conversation (TaskRun.environments)."""

    def __init__(self, conversation, place: Place):
        self.conversation, self.place = conversation, place
        self.attached = {}
        self.granted = set()
        self._lock = threading.RLock()

    # What the conversation calls.

    def handle(self, request: dict) -> dict:
        """Answer a program's request: {"value": ...} or {"error": why}."""
        action = request.get("action")
        try:
            if action == "use":
                value = self.use(str(request.get("environment") or ""), str(request.get("why") or ""),
                                 request.get("folder"))
            elif action == "release":
                value = self.release(str(request.get("environment") or ""), failed=request.get("failed"))
            elif action == "agents":
                value = self.enable_agents(str(request.get("why") or ""), asked_by="model")
            else:
                raise Refused(f"no operation {action!r}")
        except Refused as error:
            return {"error": str(error)}
        except Exception as error:
            return {"error": f"{type(error).__name__}: {error}"}
        return {"value": value}

    def of(self, name):
        """The attached environment `name`: {"env", "plain", "episode", "slot"}, or Refused."""
        found = self.attached.get(name)
        if found is None:
            raise Refused(f"{name} is not attached to this conversation")
        return found

    def any_managed(self) -> bool:
        return any(getattr(row["env"], "approval_key", None) for row in self.attached.values())

    def states(self) -> dict:
        """{name: label} of what is attached now."""
        return {name: row["label"] for name, row in self.attached.items()}

    def close(self) -> None:
        """The conversation ended: every attached environment goes back."""
        for kind in list(self.attached):
            try:
                self.release(kind, reason="the conversation ended")
            except Exception as error:
                self.conversation.trace.emit("cleanup_error", message=f"{kind}: {type(error).__name__}: {error}")

    # Attaching.

    def use(self, kind: str, why: str, folder=None) -> dict:
        conversation, trace = self.conversation, self.conversation.trace
        kinds = self.place.kinds()
        with self._lock:
            if kind in self.attached:
                return self.attached[kind]["answer"]
        primary = conversation.workspace_kind

        def refuse(reason, **detail):
            trace.emit("environment_refused", kind=kind, why=why, reason=reason, **detail)
            raise Refused(reason)

        if kind not in kinds:
            refuse(f"no installed package gives the environment {kind!r}; there are {', '.join(kinds) or 'none'}")
        label = kinds[kind].get("label") or kind
        if kind == primary:
            refuse(f"this conversation already works in {kind}: its calls are the plain ones")
        if not why:
            refuse("say why in one sentence: the user reads it when they are asked")
        if kinds[kind].get("folder") and not folder:
            refuse(f"{label} works in one folder. Ask the user which folder in plain text, then "
                   f"use_environment({kind!r}, why, folder=PATH)")
        level, skips = self.place.level(kind, conversation.config.runtime)
        asked = False
        if level == "never":
            refuse(f"the user's settings never allow taking {label} into a conversation (environments.attach). "
                   "Go on without it and say what you could not confirm.", level=level)
        with self._lock:
            granted = kind in self.granted
        if not (skips or level == "allow" or level == "ask_once_session" and granted):
            if not conversation.interactive:
                refuse(f"the user's settings ask before {label} is taken (environments.attach = {level}), and "
                       "nobody can be asked in this run. Go on without it and say what you could not confirm.",
                       level=level)
            asked = True
            target = f"use {label}" + (f" in {folder}" if folder else "")
            accepted, reason = conversation._ask_user("environment", target, why=why, environment=kind,
                                                      **({"folder": str(folder)} if folder else {}))
            if not accepted:
                refuse(f"the user did not allow {label}" + (f": {reason}" if reason else "")
                       + ". Go on without it and say what you could not confirm.", level=level, asked=True)
            if level == "ask_once_session":
                with self._lock:
                    self.granted.add(kind)
        try:
            with conversation._span("env", f"use {kind}", why=why[:200]):
                taken = self.place.begin(conversation, kind, folder, lambda: conversation._closing)
                try:
                    row = self._start(kind, label, taken)
                except BaseException:
                    taken["release"]()
                    raise
        except Refused as error:
            refuse(str(error), level=level, asked=asked)
        except Exception as error:
            refuse(f"{label} could not be prepared: {type(error).__name__}: {error}", level=level, asked=asked)
        with self._lock:
            self.attached[kind] = row
        conversation._prompt_added(row["prompt"])
        trace.emit("environment_attached", kind=kind, label=label, why=why, level=level, asked=asked,
                   skipped_confirmation=bool(skips and level not in ("allow",) and not granted),
                   **{**(taken.get("metadata") or {}), **({"folder": str(folder)} if folder else {})})
        return row["answer"]

    def _start(self, kind, label, taken) -> dict:
        """The episode of an attached environment on its worker, and what its session needs."""
        conversation = self.conversation
        env = taken["env"]
        env.tools()
        observation = env.reset(taken.get("task") or "free", conversation.seed)
        profile = env.call("profile")
        if embodiment_kind(profile) != taken["embodiment"]:
            raise RuntimeError(f"the worker drives a {embodiment_kind(profile)} embodiment, not {taken['embodiment']}")
        runtime = conversation.config.runtime
        if profile.get("physical"):
            # Whose steps these are and the run's physical-input policy: the real mouse and
            # keyboard stay under it after the environment is attached.
            identity, policy = conversation.identity or {}, dict(runtime.get("physical") or {})
            seen = dict(runtime.get("privacy") or {})
            env.call("physical", op="identify", episode_id=observation.episode_id, session=identity.get("session"),
                     agent=identity.get("agent"), level=policy.get("level"), rules=policy.get("rules") or [],
                     interactive=conversation.interactive,
                     **({"privacy": {key: seen[key] for key in ("level", "rules") if seen.get(key)}} if seen else {}))
        session = {"episode_id": observation.episode_id, "embodiment": taken["embodiment"],
                   "skills": list(taken["skills"]), "timeout_seconds": float(getattr(env, "timeout", 300.0)),
                   "host_controls": sorted(getattr(env, "host_controls", ())),
                   "reactive_budget_ms": runtime.get("reactive_budget_ms", 5.0),
                   "default_max_seconds": runtime.get("default_max_seconds", 30.0),
                   "views": {"mode": "demand", "cameras": list(KINDS[taken["embodiment"]].cameras)}}
        prompt = (f"\n\nEnvironment `{kind}` ({label}) is attached to this conversation. Its calls are the ones "
                  f"described below, each called as {kind}.NAME(...), never by the bare name; this conversation's "
                  f"own calls stay as they are. release_environment({kind!r}) gives it back."
                  + (f" {kind}.look() puts its view in your next turn; nothing of it is shown otherwise."
                     if KINDS[taken["embodiment"]].cameras else "") + "\n"
                  + (taken.get("prompt") or "").strip() + "\n")
        from harness.core.remote import RemoteEnvironment

        endpoint = getattr(env, "endpoint", None)
        return {"env": env, "episode": observation.episode_id, "label": label, "release": taken["release"],
                # Calls the worker serves to anyone go without the host's key, as the kernel
                # itself would make them.
                "plain": RemoteEnvironment(endpoint, timeout=float(getattr(env, "timeout", 300.0)))
                         if endpoint else env,
                "slot": threading.BoundedSemaphore(8), "prompt": prompt,
                "answer": {"session": session,
                           "about": f"{kind} ({label}) is attached: call it as {kind}.NAME(...). Its calls are "
                                    "described in your instructions from the next turn on; "
                                    f"print({kind}) lists them now."}}

    def release(self, kind: str, *, reason=None, failed=None) -> bool:
        with self._lock:
            row = self.attached.pop(kind, None)
        if row is None:
            return False
        conversation = self.conversation
        conversation._prompt_removed(row["prompt"])
        try:
            row["release"]()
        finally:
            conversation.trace.emit("environment_released", kind=kind, label=row["label"],
                                    **({"reason": str(reason)} if reason else {}),
                                    **({"failed": str(failed)[:300]} if failed else {}))
        return True

    # Sub-agents.

    def enable_agents(self, why: str = "", *, asked_by="user") -> dict:
        """Switch sub-agents on for this conversation: at once for the user's own switch,
        after their yes for the model's request. What the kernel loads."""
        conversation = self.conversation
        if "agents" in conversation._skills:
            return {"skills": [], "about": "Sub-agents are on already."}
        setting = self.place.agents()
        if conversation.agents is None or setting["depth"] <= 0:
            raise Refused("this conversation cannot start sub-agents (limits.agent_depth is 0, or it has no "
                          "workspaces to give them)")
        if asked_by == "model":
            if not why:
                raise Refused("say why in one sentence: the user reads it")
            if not conversation.interactive:
                raise Refused("sub-agents are off, and nobody can be asked in this run")
            accepted, reason = conversation._ask_user("agents", "switch sub-agents on for this conversation", why=why)
            if not accepted:
                conversation.trace.emit("agents_enabled", enabled=False, why=why, asked_by=asked_by, reason=reason)
                raise Refused("the user did not switch sub-agents on" + (f": {reason}" if reason else "")
                              + ". Do the task yourself.")
        added = conversation._skill_added("agents")
        conversation.trace.emit("agents_enabled", enabled=True, asked_by=asked_by, **({"why": why} if why else {}))
        return {"skills": ["agents"], "about": "Sub-agents are on: delegate(task, ...), wait_agents(), send_agent(), "
                                               "cancel_agent(). " + ("" if added else "")}
