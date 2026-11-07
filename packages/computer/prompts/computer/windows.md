
Windows in the background (Windows, macOS, Linux on X; elsewhere these calls say there is
no access). Their steps leave the user's mouse, keyboard and focus alone:

  windows()                         your windows, and the user's as far as they let you
                                    know them: {"id": "w3", "app", "title", "size",
                                    minimized, offscreen, launched, dialog_of}
  launch(app, *args, visible=False) start an app ("chrome", "TextEdit", a path) off the
                                    user's screens and work in its window; returns its row
  use_window("w3", visible=None)    work in that window; visible True or False moves one
                                    you launched onto the user's screens or off them
  elements(window=None, role=None, text=None, limit=200)   its elements in tree order
                                    (a browser's bar first): id ("e7"), role ("edit",
                                    "combobox", "button", "listitem", ...), name, value,
                                    rect (in the window's picture), actions, states;
                                    printed, one line each
  act("e7", action="click", value=None)   an element's action: click, invoke, toggle,
                                    select, expand, collapse, scroll_into_view, set_value
                                    (a field's text, a slider's number, a page's file
                                    input: a path such as "~/Documents/name.pdf")

Use the id from the intended window to distinguish same-name elements.
Element actions work in covered, off-screen and minimized windows. Input steps take
window="w3" too, their points then in that window's picture; a trace says how the step
was delivered (semantic, targeted or physical; delivered or unverified). A step only the
real mouse and keyboard can do (on Windows most key combinations; an app that ignores
background input) runs only where its window is in front, else it is refused with
"needs_physical". On macOS, input to a window not in front may be dropped.

The state's "workspace": "apps", your screenshot is your window and steps go to it;
"display", a display of your own the user never sees, needing no permission (on Linux
empty until you launch()). A display "vm-..." is a fresh virtual machine (US keyboard)
that windows(), launch() and elements() do not reach; what is saved in it is gone at the
end. Of the user's windows you learn what they allow: by default only that one is in
front (front "other").
