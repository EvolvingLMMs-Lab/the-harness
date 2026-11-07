"""The screens of the user's computer (benches/computer): with several monitors the worker
shows the one with the active window, so a window that opens on another screen is in the
next screenshot; use_screen(index) looks at one screen until use_screen() follows the
active window again. The picture keeps its size (SCREEN): a screen of another shape is
fitted into it with dark bars, where nothing can be clicked."""


class Screens:
    def screens(self):
        """The computer's screens: [{"index", "name", "size", "primary", "shown"}] (size
        in the screen's own pixels; "shown" is the one screenshots show)."""
        state = self.env.call("state", episode_id=self.episode_id)
        if state.get("screens"):
            return state["screens"]
        return [{"index": 1, "name": "screen 1", "size": list(state.get("screen", ())), "primary": True,
                 "shown": True}]

    def use_screen(self, index=None):
        """Look at and act on screen `index` from now on (screenshots and the points of
        input steps); use_screen() follows the active window again. Returns the screens."""
        self.state = self.env.call("use_screen", episode_id=self.episode_id, index=index)
        return self.screens()
