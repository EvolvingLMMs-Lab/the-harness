"""The user's real mouse and keyboard, asked for up front (benches/computer): where the
user's physical-input settings ask first (harness/physical.py), a step that needs them
waits while the user is asked; request_physical() asks before a series of steps, with
the reason the user reads."""


class Physical:
    def request_physical(self, reason, scope="app", app=None, action=None):
        """Ask for the user's real mouse and keyboard before steps that need them, where
        the policy asks first; `reason` is what you tell the user, `scope` what you ask for
        ("step", "app", "session"; the user decides what they grant), `app` (a process
        name, default the window in front) and `action` (pointer, drag, keyboard,
        clipboard, foreground) what it is for. Returns {"granted", "level", "reason"}."""
        if scope not in ("step", "app", "session"):
            raise ValueError("scope is step, app or session")
        if not self.profile.get("physical"):
            return {"granted": True, "level": None, "reason": "this workspace uses no physical input"}
        result = self.env.call("physical", op="check", episode_id=self.episode_id, app=app,
                               actions=[action] if action else None)
        if result["verdict"] in ("allow", "when_idle"):
            return {"granted": True, "level": result["level"],
                    "reason": "allowed" + (" while the user is idle" if result["verdict"] == "when_idle" else "")}
        if result["verdict"] == "refuse":
            return {"granted": False, "level": result["level"], "reason": result.get("reason")}
        answer = self.ask_physical({**result["request"], "why": str(reason)[:500], "scope": scope})
        if answer is None:
            return {"granted": False, "level": result["level"], "reason": "nobody answered"}
        return {"granted": bool(answer.get("accept")), "level": result["level"],
                "reason": answer.get("reason") or ("the user allowed it" if answer.get("accept") else
                                                   "the user said no")}


def exports(session):
    return {"request_physical": session.request_physical}
