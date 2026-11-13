"""Keep inline prompts aligned with terminal reflow."""

from prompt_toolkit.data_structures import Point
from prompt_toolkit.renderer import Renderer
from prompt_toolkit.utils import get_cwidth


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


class _ReflowOutput:
    """Keep wide-character padding zero-width in terminal reflow grids.

    tmux 3.8 can read compact padding slots as ordinary one-cell blanks on
    resize. Seed the occupied cells with narrow Unicode blanks so their
    padding keeps its zero width when replaced by the actual wide glyph.
    This changes neither the displayed text nor its final cursor position.
    """

    def __init__(self, output, screen, position):
        self._output, self._screen = output, screen
        self._x, self._y = position
        self._join_next = False

    def __getattr__(self, name):
        return getattr(self._output, name)

    def _previous_joiner(self):
        if self._screen is None:
            return False
        row = self._screen.data_buffer.get(self._y)
        if not row:
            return False
        for column in range(self._x - 1, -1, -1):
            cell = row.get(column)
            if cell is not None and cell.char:
                return cell.char.endswith("\u200d") and column + cell.width == self._x
        return False

    def cursor_forward(self, amount=1):
        self._x += amount
        self._join_next = False
        self._output.cursor_forward(amount)

    def cursor_backward(self, amount=1):
        self._x = max(0, self._x - amount)
        self._join_next = False
        self._output.cursor_backward(amount)

    def cursor_up(self, amount=1):
        self._y = max(0, self._y - amount)
        self._join_next = False
        self._output.cursor_up(amount)

    def write(self, text):
        width = get_cwidth(text)
        continuing = self._join_next
        if text:
            self._join_next = text.endswith("\u200d")
        # A joiner may end one screen cell and continue in the next write.
        # Inserting priming characters there would split the existing cluster.
        if (width > 1 and any(get_cwidth(char) > 1 for char in text)
                and not continuing and not self._previous_joiner()):
            # Autowrap is disabled: the final column can clamp the cursor,
            # so relative backward movement would start the glyph too early.
            self._output.write_raw("\x1b7")
            self._output.write("\u00a0" * width)
            self._output.write_raw("\x1b8")
        self._output.write(text)
        for char in text:
            if char == "\r":
                self._x = 0
            elif char == "\n":
                self._y += 1
            else:
                self._x += get_cwidth(char)


class ReflowInlineRenderer(Renderer):
    """Account for a macOS terminal reflowing inline rows after its width changes.

    Erase only the previous live region, preserving transcript scrollback above it.
    Windows uses its console-buffer implementation above.
    """

    def _reflow_cursor(self):
        size = self.output.get_size()
        old = self._last_size
        screen = self._last_screen
        if screen is None or old is None or old.columns == size.columns:
            return False
        width = max(1, size.columns)
        y = 0
        for index in range(self._cursor_pos.y):
            row = screen.data_buffer[index]
            end = max((x + max(cell.width, 1) for x, cell in row.items()
                       if cell.char != " " or self._style_string_has_style[cell.style]), default=0)
            y += max(1, (min(end, old.columns) + width - 1) // width)
        self._cursor_pos = Point(self._cursor_pos.x % width, y + self._cursor_pos.x // width)
        return True

    def render(self, app, layout, is_done=False):
        if self._reflow_cursor():
            super().erase(leave_alternate_screen=False)
            self.request_absolute_cursor_position()
        output = self.output
        try:
            self.output = _ReflowOutput(output, self._last_screen, self._cursor_pos)
            super().render(app, layout, is_done)
        finally:
            self.output = output

    def erase(self, leave_alternate_screen=True):
        self._reflow_cursor()
        super().erase(leave_alternate_screen)
