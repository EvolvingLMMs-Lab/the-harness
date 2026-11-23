"""A bot body's calls. Code runs on the body, in the game, at the game's speed; the call
that started it lasts as long as the code does, so reflexes go on watching and whatever
ends the call (a reflex that ends executions, its time, a cancel) ends the code too. A unit
of higher priority pauses the code (the body's worker pauses) and it goes on afterwards.
The game does not wait for anything."""

import json
import os
import re
import uuid

from harness.sdk import Escalation, Event, ExecutionTrace


# How code on the body ended, in the words every unit's end is reported with.
# A call lasts while its code runs: this is only the bound every execution has to have.
LONGEST_CALL_SECONDS = 86400.0
# Code that calls something of the bot waits for the page that says how that call works
# (calls.json: written from the pages by checks/guides_index.py). What a line of code uses:
USED = re.compile(r"\bbot\s*\.\s*(?:(creative)\s*\.\s*)?([A-Za-z_]\w*)\s*\(")
PAGES_FIRST = ("Nothing {done}: this code calls {calls}, and the pages that say how they work were not read: {pages}. "
               "{given} Read them, then give the code again in a later program.")
PAGES_COME = "They are given to you with your next message."
PAGES_ASK = ("These are given to you with your next message: {given}. Ask for the others with guide(\"name\") in "
             "a later program: one message did not have room for them.")
# The calls of code on the body that act on the game: code with none of them only reads, and
# is held to no expect (the harness's `reads`). What the body makes wait at its gate, the
# keys, an attack, the chat (a command acts), a saved routine (it may do any of these), and
# what is set on the bot.
ACTS = re.compile(
    r"\bbot\.(?:dig|placeBlock|placeEntity|equip|unequip|consume|craft|lookAt|look|activateBlock|activateEntity|"
    r"activateEntityAt|activateItem|deactivateItem|useOn|swingArm|attack|openContainer|openChest|openFurnace|"
    r"openDispenser|openEnchantmentTable|openAnvil|openVillager|openBlock|openEntity|toss|tossStack|fish|sleep|wake|"
    r"clickWindow|transfer|moveSlotItem|putAway|putSelectedItemRange|trade|mount|dismount|elytraFly|setControlState|"
    r"clearControlStates|setQuickBarSlot|chat|whisper|respawn|updateSign|writeBook|setCommandBlock|stopDigging|"
    r"closeWindow|moveVehicle|acceptResourcePack|denyResourcePack)\s*\("
    r"|\bbot\.creative\.|\bskills\b|\bh\.priority\s*\(")
_calls = None


def pages_of(code) -> dict:
    """{page: the calls of `code` it describes}, for every call of the bot that has a page."""
    global _calls
    if _calls is None:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "calls.json"), encoding="utf-8") as file:
            _calls = json.load(file)
    found = {}
    for match in USED.finditer(str(code)):
        part, name = match.groups()
        call = f"bot.{part}.{name}" if part else f"bot.{name}"
        page = _calls.get(call)
        if page and call not in found.setdefault(page, []):
            found[page].append(call)
    return found


# When the body respawns is decided when it has died, by the one who was told how: not
# beforehand, by a reflex.
RESPAWN_IS_YOURS = ("Nothing was sent: respawn() is called by your own program, not by a reflex's (this is the reflex "
                    "{reflex!r}). A dead body waits for as long as you take; respawn it when you have seen how it "
                    "died and decided what to do.")
ENDED = {"itself": "by itself", "stop": "stopped", "another job": "other code took the body",
         "death": "the body died", "restart": "the body was started again"}


def report_of(job) -> dict:
    """The bridge's record of a job as a report: `ended` says how (nothing while it runs)."""
    job = dict(job)
    running = job.get("status") == "running"
    how = None if running else "an error" if job.get("status") == "error" else ENDED.get(job.get("ended_by"), job.get("ended_by"))
    return {**({} if running else {"ended": how}),
            **{key: job.get(key) for key in ("result", "error", "logs", "events", "did", "channels", "cleared",
                                             "seconds", "paused_seconds", "expected")}}


class Body:
    def _body_call(self, call, /, **arguments):
        return self.env.call(call, episode_id=self.episode_id, **arguments)

    def _wrap_up(self):
        return []

    __wrap_up__ = _wrap_up

    def get_state(self):
        """What the body reports of itself now: connected, health, dead, food, oxygen,
        level, position, velocity, yaw, pitch, drop_below (blocks down to the ground under
        its feet), on_ground, dimension, time_of_day, raining, held, armor, inventory
        (counts by item), deaths, restarts, entities (the nearest: name, kind, distance,
        position), routines (saved), jobs (running or paused), priority (what the code that
        has the body asks for), sensed (the senses' values), sense_errors (why a sense has
        none), here and space (the position and the dimension), attempt, happened (the last
        deaths, respawns and restarts)."""
        self._observe()
        return dict(self.state)

    def get_observation(self):
        """The state and the first-person picture now ({"state", "images": {"view": data
        URL}}). To see it yourself use look("view"); this is for a program that reads it."""
        data = self._body_call("observe", cameras=["view"])
        self.state = data["state"]
        return data

    def _pages_first(self, code, done):
        """Refuse code that calls what it has not read the page of; say which pages. Code a
        reflex runs is not held to it: a node's code was checked when the node was set
        (Session.set_reflex), and when it acts nobody reads."""
        read = getattr(self, "_guides_read", None)
        if read is None:
            return
        in_reflex = getattr(self, "_in_reflex", None)
        if in_reflex is not None and in_reflex():
            return
        unread = {page: calls for page, calls in pages_of(code).items() if page not in read}
        if unread:
            # The pages come with the refusal, as far as one message has room for them.
            given = []
            for page in unread:
                try:
                    if "was not given" not in self.guide(page):
                        given.append(page)
                except Exception:
                    pass
            come = PAGES_COME if len(given) == len(unread) else PAGES_ASK.format(
                given=", ".join(f'guide("{page}")' for page in given) or "none")
            raise ValueError(PAGES_FIRST.format(
                done=done, calls=", ".join(call for calls in unread.values() for call in calls),
                pages=", ".join(f'guide("{page}")' for page in unread), given=come))

    def _run(self, skill, command, seconds, reads=False):
        # Before the first attempt there is no body in a world to run code on.
        now = self._body_call("attempt")
        if now.get("begun") is False:
            raise ValueError(f"Nothing ran: {now['why']}.")
        tag = uuid.uuid4().hex[:12]
        # The code uses the channels its unit claims (none claimed: all of them).
        unit = self._entries.current()   # (the unit this code belongs to; the root outside every other)
        claims = [name for name in (getattr(unit, "claims", ()) or ()) if name in self.channels]
        # (A node's program that uses no channel runs code that uses none: it only sets rules.)
        none = bool(getattr(unit, "channelless", False))
        command = {**command, "tag": tag, **({"channels": []} if none else {"channels": claims} if claims else {})}

        def step(state, number):
            # The first period starts the code; the call then lasts while that code runs.
            if number == 0:
                return command
            return {"type": "noop"} if tag in (state.get("jobs") or ()) else None

        try:
            # (`seconds` is how long the code is expected to take: the body tells when it has run
            # that long, and the code goes on. The call lasts while the code runs.)
            trace = self._execute(skill, {"seconds": seconds}, step, max_seconds=LONGEST_CALL_SECONDS,
                                  region=None, until=None, reads=reads)
        except Escalation as ended:
            # The call was ended (a reflex that ends executions, its time): what its code
            # had done until then goes with the event, to whoever decides what goes on.
            self._body_call("stop", id=tag)
            if isinstance(ended.trace.event.detail, dict):
                ended.trace.event.detail["report"] = self._report(tag)
            raise
        except BaseException:
            self._body_call("stop", id=tag)   # (cancelled: its code does not go on without it)
            raise
        report = self._report(tag)
        # What the code expected with h.expect counts with the program's own expects.
        noted = getattr(getattr(self, "_entries", None), "noted", None)
        for row in (report.get("expected") or ()) if noted else ():
            noted(row.get("text"), row.get("held"), row.get("found"))
        if report["ended"] == ENDED["death"]:
            # The body died under this code: the call ends with that as its event, and with it
            # the program, unless a reflex answers BODY_DIED.
            step = self.state["step"]
            self._finish(ExecutionTrace(skill, {"seconds": seconds}, step, step,
                                        Event("BODY_DIED", "body", {"report": report}, step)))
        self._observe()
        return report

    def _report(self, tag):
        """The report of the code started under `tag`, as every unit's end is reported: how
        it ended, what it returned or why it failed, and what the body says of it."""
        return report_of(self._body_call("job", id=tag, wait_seconds=1))

    def run_js(self, code, args=None, seconds=60):
        """Run JavaScript on the body and wait until it is over. `seconds` is how long you
        expect it to take: when it has run that long you are told, and it goes on (stop it
        with stop_routines()). `code` is the body of an async function with
        these names in scope: bot (a Mineflayer bot, mineflayer 4.39), Vec3, skills (the
        saved routines: await skills.name(args, log, signal)), senses (the senses, computed
        at that moment: senses.name()), sleep(ms), log(...values), signal, args, h (all of
        them are declared: do not declare these names again), and the timers. The code uses
        the channels its unit claims (move, look, use; none claimed: all three) and acts
        only on those; codes on channels of their own run at once. A unit of higher priority
        that uses one of its channels pauses it, and it goes on when that unit has ended.
        Returns the code's report: {ended (how: by itself, an error,
        stopped, other code took the body, the body died, the body was started again),
        result (its return value), error, logs, events (what happened to the body
        meanwhile), did (what the code did to the world: {dug, placed: blocks by kind,
        broke: tools, moved: blocks, pulled_back: times the server put the body back}),
        channels, cleared (the timers and listeners it had left, which
        ended with it), seconds, paused_seconds}. When the body dies the code on it is
        ended and the call ends with the event BODY_DIED."""
        self._pages_first(code, "ran")
        return self._run("run_js", {"type": "run", "code": str(code), "args": args or {},
                                    "limit": float(seconds)}, seconds, reads=not ACTS.search(str(code)))

    def routine(self, name, args=None, seconds=60):
        """Run the saved routine `name` with `args` and wait as run_js does."""
        import json

        code = f"return await skills[{json.dumps(str(name))}](args, log, signal)"
        return self._run(f"routine {name}", {"type": "run", "code": code, "args": args or {},
                                              "limit": float(seconds)}, seconds)

    def save_routine(self, name, code):
        """Keep `code` (as run_js takes it) as the routine `name` (lower case letters,
        digits, _) on the body. It stays across programs and runs; what it replaces is
        kept as a version."""
        self._pages_first(code, "was saved")
        answer = self._body_call("save_routine", routine=str(name), code=str(code))
        if "error" in answer:
            # Not kept: say so loudly, with what the body's parser said.
            raise ValueError(f"routine {name!r} was not saved ({answer['error']}). `code` is the body of the "
                             "function, as run_js takes it: statements, not a function expression.")
        return answer

    def routine_versions(self, name):
        """The earlier versions kept of the routine `name`, oldest first (each save that
        changed it kept what was there)."""
        return self._body_call("read_routine", routine=str(name)).get("versions", [])

    def read_routine(self, name, version=None):
        """The code of the saved routine `name`, as text; `version` (one of
        routine_versions(name)) reads what an earlier save held."""
        answer = self._body_call("read_routine", routine=str(name), version=version)
        if "code" not in answer:
            raise KeyError(f"no routine {name!r}: {answer.get('error', 'not saved')}")
        return answer["code"]

    def routines(self):
        """The names of the saved routines."""
        return self._body_call("routines").get("skills", [])

    def drop_routine(self, name, why):
        """Take the saved routine `name` off the body, saying `why` (what showed it wrong,
        out of date, or covered by another): later programs and runs no longer have it. Its
        code stays among its versions (routine_versions)."""
        if not str(why or "").strip():
            raise ValueError("say why the routine goes (why=): what showed it wrong, out of date, or covered by another")
        answer = self._body_call("remove_routine", routine=str(name), why=str(why))
        if "error" in answer:
            raise KeyError(f"no routine {name!r}: {answer['error']}")
        return answer

    def _nav(self, what, **arguments):
        answer = self._body_call("nav", what=what, **arguments)
        if not answer.get("ok"):
            raise ValueError(str(answer.get("error") or "the body did not take it"))
        return answer.get("listed") or {}

    def hazard(self, name, code):
        """Define the hazard `name` for the body's walking (h.go): `code` is the body of a
        JavaScript function, not async, with bot, Vec3, args and moving in scope, read at every
        tick while it is in force. It returns {zones: [...], incoming: [...]}. It stays on the
        body across programs and runs, as a sense does; avoid(name) puts it in force. Returns
        what is defined and in force (walking_rules())."""
        return self._nav("define", kind="hazard", routine=str(name), code=str(code))

    def route_rule(self, name, code):
        """Define the route rule `name`: `code` is the body of a JavaScript function, not async,
        with step, bot, Vec3 and args in scope, asked for every step of a route that is searched
        while it is in force. It returns false (the step is not taken) or the seconds it adds."""
        return self._nav("define", kind="rule", routine=str(name), code=str(code))

    def drop_walking_rule(self, name):
        """Remove the hazard or route rule `name` (it is taken out of force too)."""
        listed = self._nav("list")
        kind = "hazard" if name in listed.get("hazards", []) else "rule" if name in listed.get("rules", []) else None
        if kind is None:
            raise KeyError(f"no hazard or route rule {name!r}")
        return self._nav("undefine", kind=kind, routine=str(name))

    def avoid(self, name, args=None):
        """Put the hazard or route rule `name` in force, with `args` (plain data its code gets
        as `args`), until unavoid(name). (Code on the body puts one in force for as long as that
        code lasts: h.avoid(name, args).)"""
        return self._nav("avoid", routine=str(name), args=args)

    def unavoid(self, name):
        """Take the hazard or route rule `name` out of force."""
        return self._nav("unavoid", routine=str(name))

    def walking_rules(self):
        """{"hazards": names defined, "rules": names defined, "active": [{"name", "kind", "args",
        "owner" (the code that put it in force; None: a program, until unavoid)}], "errors":
        {name: what its code raised}}."""
        return self._nav("list")

    def code_running(self):
        """The codes that run on the body now: the report so far of each ({seconds, logs,
        did, events, channels, paused_seconds}; it has not ended); [] when no code runs. Any
        program may ask, beside the one that started the code."""
        jobs = self._body_call("body").get("jobs_running") or []
        return [report_of(self._body_call("job_by_id", id=job)) for job in jobs]

    def attempt(self, earlier=False):
        """The record of this attempt (one world from its spawn, or from the start you kept)
        as the game counted it ({"number": 0, "begun": False, "why"} before the first has
        begun): {number, began ("a new world, at its spawn", "the start you kept", or "the
        world the server plays, as it was when this session began"; game times are counted
        from there), clean, advancements: [{name, at (game time m:ss), clean}], told: [{what, at,
        clean}] (what the game told every player in the world, like "the Ender Dragon died":
        the game tells it however the thing came about, where an advancement needs the
        player's own hit), deaths, died, commands, commands_by_kind, first_command_at,
        game_time, counts (what of it counts)}.
        An attempt is clean until a command is typed in it. `earlier`: {"attempts": all of
        them, oldest first}."""
        return self._body_call("attempt", earlier=bool(earlier))

    def keep_start(self):
        """Keep the world as it is now as a start: everything in it, where the body stands,
        what it carries and wears, its health. start_over(kept=True) then begins an attempt
        from exactly that, as often as you call it. One start is kept: keeping another
        replaces it. It takes some seconds, and nothing in the game is changed by it. Returns
        {kept, in_attempt, at_game_time, position, dimension, seconds}. Raises when the body
        is dead, and where the server's worlds are not this body's to copy (it says so)."""
        return self._body_call("keep_start")

    def start_over(self, kept=False):
        """Begin an attempt, giving up the one that runs (where one does). attempt() says
        where the session stands: where the body joined a world the server already played,
        that world is the first attempt; where no world is there yet, there is none, and no
        body in one, until you begin the first.
        kept=False: a new world, at its spawn,
        with an empty inventory; it takes a minute or two. kept=True: the world as it was when
        you called keep_start(), the body in it as it was then; it takes less (the game is
        started on a copy, nothing is made anew); raises when no start is kept.
        Saved routines, the library and your notes stay. The code on the body is ended;
        reflexes and facts of this session stay. Returns {given_up: the record of the attempt
        left, now: the new one's, state}. Raises where the run is a single attempt, and
        where the server's world is not this body's to begin anew (it says so: the attempt
        that runs is then the only one)."""
        answer = self._body_call("start_over", kept=bool(kept))
        self.state = answer.pop("state")
        return answer

    def stop_routines(self):
        """End the code running on the body; returns when the body is free."""
        return self._body_call("stop")

    def body(self):
        """Everything the body reports of itself now (get_state's, with the events' count
        and what the bridge keeps besides)."""
        return self._body_call("body")

    def chat(self, text):
        """Type a line into the game chat. A line that starts with / is a command: whether
        the server obeys it is the server's to say (its answer comes in the chat)."""
        return self._body_call("chat", text=str(text))

    def respawn(self):
        """Have the dead body respawn: it is at its spawn point. As the game is sold it has
        empty hands there and what it carried lies where it died, for five minutes; a server
        may keep the inventory instead.
        A body that died stays dead until this is called, for as long as you take: call it
        when you want the body back, not at once on death. Your own program calls it: a
        reflex's program is refused. {"respawned", "dead"}, and "why" where it did not
        respawn (it is alive)."""
        unit = self._entries.current()   # (the unit this code belongs to; the root outside every other)
        while unit is not None:
            if unit.rule is not None:
                raise ValueError(RESPAWN_IS_YOURS.format(reflex=unit.rule))
            unit = unit.parent
        return self._body_call("respawn")
