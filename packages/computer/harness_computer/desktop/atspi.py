"""AT-SPI, Linux's accessibility interface, over D-Bus: the accessibility tree of an
application's window and the actions on its elements (harness/desktop/linux.py).

Applications (GTK, Qt, Chromium with its accessibility on, LibreOffice, ...) register on
the accessibility bus, a D-Bus bus of its own whose address an X display carries on its
root window (AT_SPI_BUS, set by at-spi-bus-launcher) or the session bus gives
(org.a11y.Bus). A Client walks one window's subtree (org.a11y.atspi.Accessible) and acts:
Action.DoAction, EditableText.SetTextContents, Value.CurrentValue, Selection.SelectChild,
Component.ScrollTo.

Each action is looked up by its index (Action.GetName(i)), never with Action.GetActions:
in the probe of 2026-11-01 (at-spi2-atk 2.38, GTK 3.24) GetActions made a GTK
application abort on an action without a description.

jeepney (pure Python, the computer environment's) is imported when a Client is made.
"""

import os
import threading

ACCESSIBLE = "org.a11y.atspi.Accessible"
REGISTRY = ("org.a11y.atspi.Registry", "/org/a11y/atspi/accessible/root")
# AT-SPI role names (atspi_role_get_name) as desktop.ROLES; others are "custom".
ROLE_NAMES = {
    "push button": "button", "toggle button": "button", "button": "button", "check box": "checkbox",
    "radio button": "radio", "combo box": "combobox", "text": "edit", "entry": "edit", "password text": "edit",
    "editbar": "edit", "spin button": "spinner", "slider": "slider", "scroll bar": "scrollbar",
    "progress bar": "progressbar", "menu": "menu", "popup menu": "menu", "menu bar": "menubar",
    "menu item": "menuitem", "check menu item": "menuitem", "radio menu item": "menuitem",
    "tear off menu item": "menuitem", "page tab": "tabitem", "page tab list": "tab", "list": "list",
    "list box": "list", "list item": "listitem", "table": "table", "tree table": "tree", "tree": "tree",
    "tree item": "treeitem", "table cell": "dataitem", "table row": "dataitem", "column header": "headeritem",
    "row header": "headeritem", "table column header": "headeritem", "table row header": "headeritem",
    "header": "header", "label": "text", "static": "text", "paragraph": "text", "heading": "text",
    "caption": "text", "image": "image", "icon": "image", "link": "link", "tool bar": "toolbar",
    "status bar": "statusbar", "tool tip": "tooltip", "frame": "window", "window": "window", "dialog": "window",
    "alert": "window", "file chooser": "window", "panel": "pane", "filler": "pane", "scroll pane": "pane",
    "viewport": "pane", "split pane": "pane", "layered pane": "pane", "internal frame": "pane", "section": "group",
    "form": "group", "grouping": "group", "group": "group", "document web": "document",
    "document frame": "document", "document text": "document", "document email": "document",
    "document spreadsheet": "document", "document presentation": "document", "calendar": "calendar",
    "separator": "separator", "title bar": "titlebar"}
# Roles a click toggles, and those a click selects.
TOGGLED = {"check box", "toggle button", "check menu item"}
SELECTED = {"radio button", "radio menu item"}
# Action names that stand for a click (lower case), in the order they are preferred (GTK:
# click, activate; Chromium: press, jump, check, uncheck, select; Qt: press, toggle).
INVOKE_NAMES = ("click", "press", "jump", "activate", "dodefault", "open", "default", "check", "uncheck", "toggle",
                "select")
# Roles whose "activate" is their Enter key, not a click.
TYPED = {"text", "entry", "password text", "editbar", "spin button", "combo box"}
EXPAND_NAMES = ("expand or contract", "toggle", "expand", "collapse", "expandorcollapse")
# StateType bits (at-spi2 atspi-constants.h).
STATES = {"active": 1, "checked": 4, "collapsed": 5, "defunct": 6, "editable": 7, "enabled": 8, "expandable": 9,
          "expanded": 10, "focused": 12, "selected": 23, "sensitive": 24, "showing": 25, "visible": 30,
          "indeterminate": 32, "required": 33, "invalid_entry": 36, "read_only": 43, "checkable": 41}
# How far (pixels) an accessible's edges may be from its window's frame when its name is not
# the window's title (the frame's title bar and borders are not the accessible's).
NEAR = 64
# Roles whose texts are a list's, not what a dropdown shows (its open menu).
LISTS = {"list", "listitem", "menu", "menuitem", "tree", "treeitem"}
# D-Bus errors that mean the element (or its application) is gone.
GONE_ERRORS = ("org.freedesktop.DBus.Error.UnknownObject", "org.freedesktop.DBus.Error.ServiceUnknown",
               "org.freedesktop.DBus.Error.NoReply", "org.freedesktop.DBus.Error.UnknownMethod",
               "org.freedesktop.DBus.Error.Disconnected")


class Gone(LookupError):
    """The element or its application is gone."""


def states_of(words) -> set:
    """The names of the states set in GetState's two 32-bit words."""
    low, high = (list(words) + [0, 0])[:2]
    bits = int(low) | int(high) << 32
    return {name for name, bit in STATES.items() if bits >> bit & 1}


def bus_address(root_property: bytes | str | None = None) -> str | None:
    """The accessibility bus: the display's AT_SPI_BUS property, $AT_SPI_BUS_ADDRESS, or
    what the session bus says (org.a11y.Bus.GetAddress)."""
    if root_property:
        return root_property.decode("utf-8") if isinstance(root_property, bytes) else str(root_property)
    if os.environ.get("AT_SPI_BUS_ADDRESS"):
        return os.environ["AT_SPI_BUS_ADDRESS"]
    if not os.environ.get("DBUS_SESSION_BUS_ADDRESS"):
        return None
    try:
        from jeepney import DBusAddress, new_method_call
        from jeepney.io.blocking import open_dbus_connection

        with open_dbus_connection(bus="SESSION") as session:
            reply = session.send_and_get_reply(new_method_call(DBusAddress("/org/a11y/bus", "org.a11y.Bus",
                                                                           "org.a11y.Bus"), "GetAddress"), timeout=3)
        return str(reply.body[0]) if reply.body else None
    except Exception:
        return None


class Client:
    """One connection to the accessibility bus at `address`."""

    def __init__(self, address: str, timeout: float = 5.0):
        try:
            from jeepney.io.blocking import open_dbus_connection
        except ImportError as error:
            raise RuntimeError("the Linux desktop backend needs jeepney (the computer environment installs it)") \
                from error
        self.address = address
        self.timeout = float(timeout)
        self._connection = open_dbus_connection(bus=address)
        self._lock = threading.Lock()
        self._pids = {}

    def close(self) -> None:
        try:
            self._connection.close()
        except OSError:
            pass

    # -- D-Bus ------------------------------------------------------------------------------

    def call(self, name, path, interface, method, signature=None, body=()):
        from jeepney import DBusAddress, MessageType, new_method_call

        message = new_method_call(DBusAddress(path, bus_name=name, interface=interface), method, signature,
                                  tuple(body))
        with self._lock:
            reply = self._connection.send_and_get_reply(message, timeout=self.timeout)
        if reply.header.message_type == MessageType.error:
            from jeepney import HeaderFields

            error = reply.header.fields.get(HeaderFields.error_name, "")
            text = reply.body[0] if reply.body else error
            if error in GONE_ERRORS:
                raise Gone(f"{interface.rsplit('.', 1)[-1]}.{method}: {text}")
            raise RuntimeError(f"{interface.rsplit('.', 1)[-1]}.{method}: {text}")
        return reply.body

    def get(self, name, path, interface, key):
        value = self.call(name, path, "org.freedesktop.DBus.Properties", "Get", "ss", (interface, key))[0]
        return value[1] if isinstance(value, tuple) else value

    def set(self, name, path, interface, key, signature, value):
        self.call(name, path, "org.freedesktop.DBus.Properties", "Set", "ssv", (interface, key, (signature, value)))

    # -- applications and windows -----------------------------------------------------------

    def applications(self) -> list[tuple]:
        """The registered applications: (bus name, path)."""
        return [tuple(child) for child in self.call(*REGISTRY, ACCESSIBLE, "GetChildren")[0]]

    def pid(self, name) -> int | None:
        if name not in self._pids:
            try:
                self._pids[name] = int(self.call("org.freedesktop.DBus", "/org/freedesktop/DBus",
                                                 "org.freedesktop.DBus", "GetConnectionUnixProcessID", "s",
                                                 (name,))[0])
            except (RuntimeError, LookupError, OSError, TimeoutError):
                self._pids[name] = None
        return self._pids[name]

    def frame(self, pid, title, rect) -> tuple | None:
        """The top-level accessible of the window of process `pid` with `title` (and frame
        rect [l, t, r, b]): its application's child of that name, else the one whose
        extents are closest to the rect (its frame's edges within NEAR pixels), else None:
        no such application registered, or a window of it with no accessible of its own (a
        Chromium's GTK file chooser), which is never given another window's."""
        candidates = []
        for name, path in self.applications():
            if self.pid(name) != pid:
                continue
            try:
                for child in self.call(name, path, ACCESSIBLE, "GetChildren")[0]:
                    candidates.append(tuple(child))
            except (RuntimeError, LookupError, TimeoutError):
                continue
        if not candidates:
            return None
        named = []
        for name, path in candidates:
            try:
                if self.get(name, path, ACCESSIBLE, "Name") == title:
                    named.append((name, path))
            except (RuntimeError, LookupError, TimeoutError):
                continue
        if len(named) == 1:
            return named[0]

        def distance(child):
            try:
                x, y, width, height = self.call(*child, "org.a11y.atspi.Component", "GetExtents", "u", (0,))[0]
            except (RuntimeError, LookupError, TimeoutError):
                return float("inf")
            return max(abs(x - rect[0]), abs(y - rect[1]), abs(x + width - rect[2]), abs(y + height - rect[3]))

        best = min(named or candidates, key=distance)
        return best if named or distance(best) <= NEAR else None

    # -- the tree -------------------------------------------------------------------------------

    def tree(self, top: tuple, window_handle, limit: int = 600) -> list[dict]:
        """The elements of the subtree at `top`, depth first (desktop.Backend's Element
        rows), at most `limit`."""
        elements = []

        def walk(node, depth, parent):
            if len(elements) >= limit:
                return
            try:
                row = self.element(node, depth, parent, window_handle)
            except Gone:
                if depth == 0:
                    raise
                return
            except (RuntimeError, TimeoutError):
                return
            index = len(elements)
            elements.append(row)
            if row["_defunct"]:
                return
            try:
                children = self.call(*node, ACCESSIBLE, "GetChildren")[0]
            except (RuntimeError, LookupError, TimeoutError):
                return
            for child in children:
                walk(tuple(child), depth + 1, index)

        walk(tuple(top), 0, None)
        _shown_values(elements)
        for row in elements:
            row.pop("_defunct", None)
            row.pop("_placeholder", None)
        return elements

    def element(self, node, depth, parent, window_handle) -> dict:
        name, path = node
        role_name = str(self.call(name, path, ACCESSIBLE, "GetRoleName")[0])
        interfaces = set(self.call(name, path, ACCESSIBLE, "GetInterfaces")[0])
        states = states_of(self.call(name, path, ACCESSIBLE, "GetState")[0])
        label = str(self.get(name, path, ACCESSIBLE, "Name") or "")
        rect = [0, 0, 0, 0]
        if "org.a11y.atspi.Component" in interfaces:
            x, y, width, height = self.call(name, path, "org.a11y.atspi.Component", "GetExtents", "u", (0,))[0]
            rect = [int(x), int(y), int(x) + int(width), int(y) + int(height)]
        names = []
        if "org.a11y.atspi.Action" in interfaces:
            count = int(self.get(name, path, "org.a11y.atspi.Action", "NActions") or 0)
            for number in range(min(count, 12)):
                try:
                    names.append(str(self.call(name, path, "org.a11y.atspi.Action", "GetName", "i", (number,))[0]))
                except (RuntimeError, TimeoutError):
                    names.append("")
        role = ROLE_NAMES.get(role_name, "custom")
        actions, shown = [], []
        lower = [action.lower().replace("_", "").replace("-", " ") for action in names]
        clickable = next((action for action in INVOKE_NAMES if action in lower
                          and not (role_name in TYPED and action == "activate")), None)
        if role_name in TOGGLED and clickable:
            actions.append("toggle")
        elif role_name in SELECTED and clickable:
            actions.append("select")
        elif clickable:
            actions.append("invoke")
        expander = next((action for action in EXPAND_NAMES if action in lower), None)
        if "expandable" in states:
            if expander or clickable:
                actions.append("collapse" if "expanded" in states else "expand")
            shown.append("expanded" if "expanded" in states else "collapsed")
        if role_name in ("list item", "page tab", "tree item", "table cell", "table row") and "select" not in actions:
            actions.append("select")
        password = role_name == "password text"
        value = None
        if "org.a11y.atspi.EditableText" in interfaces and "editable" in states and "read_only" not in states:
            actions.append("set_value")
        elif "org.a11y.atspi.Value" in interfaces and "read_only" not in states and role in (
                "slider", "spinner", "scrollbar"):
            actions.append("set_value")
        if role in ("edit", "combobox", "spinner") and "org.a11y.atspi.Text" in interfaces and not password:
            try:
                value = str(self.call(name, path, "org.a11y.atspi.Text", "GetText", "ii", (0, -1))[0])
            except (RuntimeError, TimeoutError):
                value = None
        elif "org.a11y.atspi.Value" in interfaces and role in ("slider", "spinner", "progressbar", "scrollbar"):
            try:
                value = f"{float(self.get(name, path, 'org.a11y.atspi.Value', 'CurrentValue')):g}"
            except (RuntimeError, TimeoutError, TypeError, ValueError):
                value = None
        if "org.a11y.atspi.Component" in interfaces and "showing" not in states and depth:
            actions.append("scroll_into_view")
        if role_name in TOGGLED or "checkable" in states:
            shown.append("mixed" if "indeterminate" in states else "checked" if "checked" in states else "unchecked")
        if "selected" in states:
            shown.append("selected")
        if "enabled" not in states and "sensitive" not in states:
            shown.append("disabled")
        if "focused" in states:
            shown.append("focused")
        if "showing" not in states:
            shown.append("offscreen")
        if role == "edit" and ("read_only" in states or "editable" not in states):
            shown.append("readonly")
        if "required" in states:
            shown.append("required")
        if "invalid_entry" in states:
            shown.append("invalid")
        placeholder = None
        if role == "combobox" and not value:
            # A script-built dropdown points its description at its placeholder while
            # nothing is chosen (aria-describedby): what it shows is then not a value.
            try:
                placeholder = str(self.get(name, path, ACCESSIBLE, "Description") or "") or None
            except (RuntimeError, TimeoutError):
                placeholder = None
        if password:
            shown.append("password")
        return {"key": (name, path), "ref": {"bus": name, "path": path, "actions": names, "role": role_name,
                                             "interfaces": sorted(interfaces), "parent": None},
                "window": window_handle, "role": role, "name": label, "value": value or None, "rect": rect,
                "actions": actions, "states": shown, "depth": depth, "parent": parent,
                "_defunct": "defunct" in states, "_placeholder": placeholder}

    # -- actions ----------------------------------------------------------------------------------

    def act(self, element: dict, action: str, value=None) -> str:
        """Do `action` on `element`; how (the method), or RuntimeError; Gone when it is."""
        ref = element["ref"]
        name, path = ref["bus"], ref["path"]
        lower = [item.lower().replace("_", "").replace("-", " ") for item in ref.get("actions") or ()]

        def do(candidates):
            for candidate in candidates:
                if candidate in lower:
                    index = lower.index(candidate)
                    done = self.call(name, path, "org.a11y.atspi.Action", "DoAction", "i", (index,))[0]
                    if not done:
                        raise RuntimeError(f"the application refused its action {ref['actions'][index]!r}")
                    return f"at-spi Action.DoAction({ref['actions'][index]})"
            return None

        if action in ("invoke", "toggle"):
            method = do(INVOKE_NAMES)
        elif action == "select":
            method = self._select(name, path) or do(INVOKE_NAMES)
        elif action in ("expand", "collapse"):
            states = states_of(self.call(name, path, ACCESSIBLE, "GetState")[0])
            if "expandable" not in states:
                method = None
            elif ("expanded" in states) == (action == "expand"):
                return f"at-spi: already {action}ed"
            else:
                method = do(EXPAND_NAMES) or do(INVOKE_NAMES)
        elif action == "set_value":
            method = self._set_value(name, path, ref, value)
        elif action == "scroll_into_view":
            self.call(name, path, "org.a11y.atspi.Component", "ScrollTo", "u", (4,))  # ATSPI_SCROLL_ANYWHERE
            method = "at-spi Component.ScrollTo"
        else:
            raise ValueError(f"an element's action is one of invoke, toggle, select, expand, collapse, set_value, "
                             f"scroll_into_view, not {action!r}")
        if method is None:
            raise RuntimeError(f"it has no action for {action}" + (f" (it has {', '.join(ref['actions'])})"
                                                                     if ref.get("actions") else ""))
        return method

    def _select(self, name, path) -> str | None:
        """Select the element in its parent's Selection, where the parent has one."""
        parent = self.get(name, path, ACCESSIBLE, "Parent")
        if not parent:
            return None
        parent = tuple(parent)
        interfaces = set(self.call(*parent, ACCESSIBLE, "GetInterfaces")[0])
        if "org.a11y.atspi.Selection" not in interfaces:
            return None
        index = int(self.call(name, path, ACCESSIBLE, "GetIndexInParent")[0])
        if not self.call(*parent, "org.a11y.atspi.Selection", "SelectChild", "i", (index,))[0]:
            raise RuntimeError("its list refused to select it")
        return "at-spi Selection.SelectChild"

    def _set_value(self, name, path, ref, value) -> str:
        interfaces = set(ref.get("interfaces") or self.call(name, path, ACCESSIBLE, "GetInterfaces")[0])
        if "org.a11y.atspi.EditableText" in interfaces:
            if not self.call(name, path, "org.a11y.atspi.EditableText", "SetTextContents", "s", (str(value),))[0]:
                raise RuntimeError("the application refused the text")
            return "at-spi EditableText.SetTextContents"
        if "org.a11y.atspi.Value" in interfaces:
            self.set(name, path, "org.a11y.atspi.Value", "CurrentValue", "d", float(value))
            return "at-spi Value.CurrentValue"
        raise RuntimeError("it takes no value")


def _shown_values(rows: list[dict]) -> None:
    """A dropdown with no value of its own (a web page's script-built one: its text box stays
    empty) takes the text it shows: the texts beside it in its nearest container (its
    parent, else that one's), not those of its open list, unless that text is its
    placeholder."""
    children = {}
    for index, row in enumerate(rows):
        children.setdefault(row["parent"], []).append(index)

    def texts(index, skip, label):
        found = []
        for child in children.get(index, ()):
            row = rows[child]
            if child == skip or row["role"] in LISTS:
                continue
            if row["role"] == "text" and row["name"].strip() and row["name"].strip() != label:
                found.append(row["name"])
            found += texts(child, skip, label)
        return found

    for index, row in enumerate(rows):
        if row["role"] != "combobox" or row["value"]:
            continue
        container = row["parent"]
        for _ in range(2):
            if container is None:
                break
            shown = " ".join("".join(texts(container, index, row["name"].strip())).split())
            if shown:
                if shown != (row.get("_placeholder") or "").strip():
                    row["value"] = shown
                break
            container = rows[container]["parent"]
