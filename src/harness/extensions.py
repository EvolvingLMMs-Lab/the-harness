"""What packages add to the session host and its frontends. A package names a module of its
own in package.toml ([provides] host = "module"); the core calls what that module defines
by name and imports no package itself. A host module may define:

    Workspaces(directory, settings)   a WorkspaceProvider (harness.sdk). All installed
                                      providers participate: kinds, selection, binding,
                                      configuration, provisioning and release belong to
                                      the package. Duplicate kind names are rejected;
                                      the core never falls back to a built-in backend.
    note(values) -> str               a line about this computer over the terminal chat's /settings
    waiting(owner) -> str | None      what an agent of a session waits for (the input lock)
    recording(directory) -> dict      a run's screen recording ({"path", "start", "stop",
                                      "area"}), or None
    areas(text) -> tuple              a screen area "x,y,width,height" as numbers
    Chromes(directory, limit)         the headless Chromes a suite's background browsers share
    overlay                           the timeline overlay (the app package's: a window on top of
                                      the screen; launch, for_session, for_runs, close, Options)
    focus() -> bool                   bring the package's window to the front (the app's, taptab's);
                                      False when it is not open (focus() tries each in turn)
    session_adapter(name, directory, *, cwd, isolation, model, effort)
                                      a host-managed external conversation, or None for a name
                                      this package does not provide. Its trace lives in directory.
    model_backend(config)             the transport of a model role (runtime/decision/model.py
                                      MODEL_KEYS) whose `backend` this package provides, or None
                                      for another backend: called like a Chat Completions request
                                      (url, headers, payload, timeout), it answers in that shape.
                                      `streams_text` true: it takes on_text; `cancellable` true:
                                      it takes cancellation
    pages                             the package's pages: {"/taptab": "taptab.html"}, files of its
                                      ui/static/ served at those paths (host/http.py); its other
                                      files are at /static/<package>/<file>
    api                               the package's API: {"inbox": handler}, served at
                                      /api/<package>/inbox with the session key; handler(server,
                                      data) -> JSON, or (body, content type, headers) as it is
                                      (data: a GET's query, a POST's JSON body; a ValueError or
                                      KeyError answers 400 with its text)
    mcp_servers(app) -> dict          MCP servers for the conversations of the session host's
                                      assistant (the app's connectors), {name: client config};
                                      close_app(app) when the assistant closes
    export_video(directory, ...)      a run as a video, used by a frontend command
    profiles                          {name: path}: conversation profiles a frontend starts the
                                      assistant's conversations with (POST /api/app/conversations
                                      {profile}); each file names skills only its conversations
                                      have and prompt text (host/assistant.py PROFILE_KEYS)
    background(server)               a service with start(), close(), and keep_alive().
                                     Optionally registered(run, conversation) is called
                                     after session registration, before execution.

Standard library only.
"""

import importlib

_CACHE = {}
_PROBLEMS = {}


def hosts() -> list:
    """(package, host module) of the packages this process uses that give one, in their
    order (paths.packages)."""
    from .paths import packages

    found = packages()
    roots = tuple(package.path for package in found)
    if roots not in _CACHE:
        _CACHE.clear()
        _PROBLEMS.clear()
        loaded = []
        for package in found:
            if "host" not in package.provides:
                continue
            try:
                loaded.append((package, importlib.import_module(package.provides["host"][0])))
            except Exception as error:  # a package made for another harness: it alone is left out
                _PROBLEMS[package.name] = (f"{package.name} {package.version} was skipped: its host module did not "
                                           f"import ({type(error).__name__}: {error}): harness install --update")
        _CACHE[roots] = loaded
    return _CACHE[roots]


def host_problems() -> dict:
    """{package: why its host module was left out} of the last hosts()."""
    return dict(_PROBLEMS)


def modules() -> list:
    """The host modules of the packages this process uses, in their order (paths.packages)."""
    return [module for _, module in hosts()]


def first(name: str):
    """What the first host module that defines `name` has under it, or None."""
    for module in modules():
        value = getattr(module, name, None)
        if value is not None:
            return value
    return None


def require(name: str, what: str, provider: str):
    """What `name` is in a host module, installing the package that provides `provider` among
    its `what` first (as packages.auto_install says) when none has it: the app package's
    overlay for the frontends that open one."""
    value = first(name)
    if value is None:
        from .packages import Packages, activate

        packages = Packages()
        packages.ensure(what, provider, log=lambda message: None)
        activate(packages)  # its folder on the import path, its host module found
        value = first(name)
    if value is None:
        raise ValueError(f"no package gives {name} (harness install {provider})")
    return value


def focus() -> bool:
    """Bring a frontend's window to the front when a conversation needs the user: each host
    module's focus() in turn, until one finds its window open (the app's, then another
    package's page). Whether one did."""
    for module in modules():
        function = getattr(module, "focus", None)
        if function is not None and function():
            return True
    return False


def overlay():
    """The timeline overlay (the app package's harness_app/overlay.py), provided by an installed frontend."""
    window = first("overlay")
    if window is None:
        raise ValueError("No installed frontend provides an overlay")
    return window
