"""The session of a bot body: programs act by running code on the body. A call that runs
code is an execution like any other: it lasts while its job runs on the body, the reflexes
watch it every period, and a unit of higher priority takes the body from it: the body's
worker pauses, so that code waits where it is and goes on afterwards. The body ends
every job that is told to stop (by force when its code does not return). What happens to
the body by itself (it died, it left its dimension, it was started again) goes to the
handlers as the environment's own events; the body's death the worker tells the run when it
happens (benches/mineflayer/runtime.py), which puts it before the model at once with the
pictures before it."""

import time

from harness.sdk import EpisodeCore, Event


class BodySession(EpisodeCore):
    embodiment = "botbody"
    show_format = "jpeg"
    # The body's channels: codes that use channels of their own run at once, and a unit of
    # higher priority pauses only the codes that share one with it (runtime/tick.py).
    channels = {"move": "the movement keys", "look": "where the head turns",
                "use": "the hand: dig, place, hit, use an item, the inventory and windows"}

    def can_act(self, state):
        """A dead body cannot act, and neither can one that is in no world yet (no attempt has begun: the
        worker's state says can_act false): nothing of the tree is judged until it can."""
        return state.get("can_act") is not False and not state.get("dead")

    def _combine(self, commands):
        """The run commands of codes started in one period, as one command."""
        started = [command for command in commands if command and command.get("type") != "noop"]
        if not started:
            return {"type": "noop"}
        return started[0] if len(started) == 1 else {"type": "batch", "commands": started}
    observation_event_kinds = frozenset({"body_died", "body_changed_dimension", "body_restarted"})

    def _embodiment_setup(self, options):
        self._told = 0.0     # the time of the last notable event the handlers heard of
        self._began = time.monotonic()

    def _tick(self, command, cameras=None):
        receipt = self.env.call("tick", episode_id=self.episode_id, step=self.state["step"], command=command)
        self.state = receipt["state"]
        return receipt

    def _base_command(self, state):
        return {"type": "noop"}

    def _reactive_view(self, state, tick):
        """What a rule sees: the body as it reports itself (health, food, position, velocity,
        drop_below, on_ground, dimension, held, inventory), the entities near it, its saved
        routines and running jobs, and `t`, the seconds since the session began."""
        view = {key: value for key, value in state.items() if key not in ("step_limit", "screen", "happened")}
        # The session's own clock: the tick count the harness passes starts again with every
        # execution and stands at 0 while no code runs.
        view["t"] = time.monotonic() - self._began
        return view

    def _take_observation_events(self, state):
        events = []
        for item in state.get("happened") or ():
            if item["t"] <= self._told:
                continue
            self._told = item["t"]
            kind = {"death": "body_died", "respawn_or_dimension": "body_changed_dimension",
                    "body_restarted": "body_restarted"}.get(item["kind"])
            if kind:
                events.append(Event(kind, "body", {"at": item["t"], **{k: v for k, v in item.items()
                                                                        if k not in ("kind", "t")}}, state["step"]))
        return tuple(events)

    def _sample(self, state):
        return {"step": state["step"], "health": state.get("health"), "position": state.get("position")}

    def _outside(self, region, state):
        return False
