
Coordinates are screenshot pixels from the top left, SCREEN = (width, height).
get_observation() returns Screenshot (.image RGB, .size, .state); show() a crop
.image[y0:y1, x0:x1], where (u, v) means (x0 + u, y0 + v).
Rule view["events"] carries window_opened, window_closed, dialog_appeared,
focus_changed, page_loaded and navigation_failed records by "kind". Use on(kind, handler)
for a notice or watch/when for a condition. Rule commands wrap input dicts,
e.g. {"command": {"type": "key", "keys": ["escape"]}}, or "type": "click" with x/y,
"type": "type" with text.

Input steps, each one step of the step limit, return a trace (.ok, .event.kind,
.event.detail); the screen settles briefly after each:

  click(x, y, button="left", count=1)   button "right"; count 2 a double click
  drag(x, y, to_x, to_y, seconds=0.4)   press, move, release
  scroll(direction, amount=5, x=None, y=None)   "up", "down", "left", "right" wheel
                                    clicks, over (x, y)
  type_text(text)                   type at the keyboard focus ("\n" Enter, "\t" Tab)
  press(*keys)                      keys together: press("ctrl", "s"); pyautogui's names
  wait(seconds=1.0)                 up to 10 s

A rejected step carries SHIELD_REJECTED and the shield's reasons. An unverified
delivery may already have had an effect. Observe before choosing the next action.
