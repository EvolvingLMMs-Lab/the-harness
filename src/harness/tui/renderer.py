"""Keep an inline prompt's erase origin aligned with Windows console reflow."""

from prompt_toolkit.data_structures import Point
from prompt_toolkit.renderer import Renderer


class WindowsInlineRenderer(Renderer):
    """ConPTY reflows painted rows before prompt_toolkit sees the new size.

    prompt_toolkit's cached cursor is relative to the old physical rows. Both
    resize erases and ordinary refreshes must account for the extra rows before
    using it, otherwise the top of the prompt becomes permanent scrollback.
    """

    _console_width = None

    def _reflow_cursor(self):
        width = self.output.get_win32_screen_buffer_info().dwSize.X
        old_width, self._console_width = self._console_width, width
        screen = self._last_screen
        if screen is None or old_width is None or width == old_width:
            return False

        # The renderer writes hard line breaks with autowrap disabled. Each
        # painted row is therefore independently reflowed by the console.
        y = 0
        for row_index in range(self._cursor_pos.y):
            row = screen.data_buffer[row_index]
            end = max((index + max(cell.width, 1) for index, cell in row.items()
                       if cell.char != " " or self._style_string_has_style[cell.style]), default=0)
            end = min(end, self._last_size.columns)
            y += max(1, (end + width - 1) // width)
        y += self._cursor_pos.x // width
        self._cursor_pos = Point(self._cursor_pos.x % width, y)
        return True

    def render(self, app, layout, is_done=False):
        if self._reflow_cursor():
            super().erase(leave_alternate_screen=False)
            self.request_absolute_cursor_position()
        super().render(app, layout, is_done)

    def erase(self, leave_alternate_screen=True):
        self._reflow_cursor()
        super().erase(leave_alternate_screen)

