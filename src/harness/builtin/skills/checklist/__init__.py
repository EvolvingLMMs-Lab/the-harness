"""A plan the user sees while the agent works: the task's steps, checked off as the
programs do them. The steps go to the host as they change (core/spans.py notes), so the
page shows them while a program still runs."""

from harness.sdk import spans


class Checklist:
    def plan(self, *steps):
        """Show the user your plan: the task's steps in order, short and in their language,
        as strings (or one list). Call it again to change the plan; the steps done so far
        stay checked when their text is the same. Returns the number of steps."""
        if len(steps) == 1 and isinstance(steps[0], (list, tuple)):
            steps = tuple(steps[0])
        items = [" ".join(str(step).split()) for step in steps if str(step).strip()]
        if not items:
            raise ValueError("plan() takes the steps of the task")
        done = {entry["step"] for entry in self.__dict__.get("_plan", []) if entry["done"]}
        self._plan = [{"step": step, "done": step in done} for step in items]
        self._send_plan()
        return len(items)

    def step_done(self, number):
        """Check off step `number` of your plan (1 for the first)."""
        steps = self.__dict__.get("_plan") or []
        if not 1 <= int(number) <= len(steps):
            raise ValueError(f"the plan has steps 1 to {len(steps)}" if steps else "call plan() first")
        steps[int(number) - 1]["done"] = True
        self._send_plan()

    def _send_plan(self):
        spans.note("plan", steps=[dict(entry) for entry in self._plan])
