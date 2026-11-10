"""User decisions at the point a computer workspace is requested."""

# The computer's kinds as a conversation's environment choice offers them (host.py describe).
KINDS = {
    "browser": ("Background browser", "isolated browser, no control of your mouse or keyboard"),
    "apps": ("Background applications", "may need foreground input; that permission is chosen separately"),
    "desktop": ("Your desktop", "sees your screen and may use your real mouse and keyboard"),
    "display": ("Separate desktop", "its own display or VM; requires a configured environment"),
}

CHOICES = {
    ("physical", "level"): ("May Harness use your real mouse and keyboard?", [
        ("never", "Never — refuse operations that need your mouse or keyboard"),
        ("ask_each", "Ask before each input operation"),
        ("ask_once_app", "Ask once per application"),
        ("ask_once_session", "Ask once per session"),
        ("when_idle", "Allow while you are idle"),
        ("allow", "Allow without asking for each input operation"),
    ]),
    ("privacy", "level"): ("What may the model learn about other windows?", [
        ("none", "Nothing about other windows"),
        ("presence", "Only whether another window is in front"),
        ("apps", "Application names too"),
        ("titles", "Application names and window titles"),
    ]),
    ("computer", "record_screen"): ("Save screen recordings for these tasks?", [
        ("off", "Do not record screen video"),
        ("on", "Save screen video locally where supported — it can include visible private information"),
    ]),
}


def require(settings, section, key, *, override=None, allowed=None):
    title, rows = CHOICES[section, key]
    options = [{"value": value, "label": label} for value, label in rows
               if allowed is None or value in allowed]
    return settings.require_choice(section, key, title=title, options=options, override=override)


def for_workspace(settings, kind, runtime=None):
    runtime = runtime or {}
    if kind in ("desktop", "apps"):
        require(settings, "physical", "level", override=(runtime.get("physical") or {}).get("level"))
        require(settings, "privacy", "level", override=(runtime.get("privacy") or {}).get("level"))
    require(settings, "computer", "record_screen")
