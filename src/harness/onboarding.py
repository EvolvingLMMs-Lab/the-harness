"""The first run, the same in every frontend: what on this computer can be the agent's
model (found), one real call with the chosen one (tryout), and keeping it (choose).

Three things are told apart everywhere, as Claude Code's /model and Zed's model selector
tell them apart: the source (whose account pays: an agent's command line signed in here, a
provider's API key, this computer), the model (one of those the source offers), and the
reasoning effort (one of the levels that model has). A source is never shown as a model.

A source is one of three kinds, and any of them alone is enough:

- an agent's command line that is signed in here (Claude Code, Codex, Gemini CLI, Grok,
  any agent that speaks the Agent Client Protocol): it runs under the user's own plan,
  through ACP; its sign-in stays its own, nothing of it is read or kept here;
- a provider's API key (found in the environment or in the credentials, or typed);
- a model that runs on this computer.

What a source offers (offered) is asked of the source itself: an agent declares its models
and each model's effort levels through ACP, a provider lists them in its catalog. Choosing
a source keeps one of its models, by name, with that model's effort levels; any other of
its models is one choice away in every model list.

The agents people use most are always listed, one that is not on this computer with how to
get it, and the rest of the ACP Registry is one row further; nothing is chosen for the user
and no other vendor's command line is installed. A key that works is kept in the credentials
file even when it came from the environment: a session host started at login does not see
the variables of the user's shell.

Standard library only.
"""

import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from urllib.request import urlopen

from . import providers
from .problems import Problem

MARK = "onboarded.json"
TRY_SYSTEM = "You are being tried out. Reply with the single word: ok"
TRY_MESSAGE = [{"role": "user", "content": "Reply with the single word: ok"}]


def marker(directory: Path) -> Path:
    return Path(directory) / MARK


def done(directory: Path) -> None:
    """Remember that the first run was gone through here."""
    from . import __version__
    from .core import atomic_write

    atomic_write(marker(directory), json.dumps({"at": time.time(), "version": __version__}))


def needed(directory: Path) -> bool:
    """Whether the first run is still to do: it was not gone through here, and either no
    model was ever chosen, or the one chosen has its key in the shell's environment only (a
    session host started at login could not use it). A model list that does not read, or one
    emptied on purpose, is repaired where it is edited, not set up again."""
    directory = Path(directory)
    if marker(directory).is_file():
        return False
    try:
        selected = _selected(directory)
    except ValueError:
        return False
    if selected is None:
        return not (directory / "models.json").exists()
    return not _key_kept(directory, selected)


def kept_ready(directory: Path) -> bool:
    """Whether the chosen model works for a process that has only the files of `directory`."""
    try:
        selected = _selected(Path(directory))
    except ValueError:
        return False
    return selected is not None and _key_kept(Path(directory), selected)


def _selected(directory: Path) -> dict | None:
    from . import model_list

    return model_list.select(directory, native=True)


def _key_kept(directory: Path, selected: dict) -> bool:
    from .settings import Credentials

    provider = providers.PROVIDERS.get(selected["provider"])
    if provider is None or not providers.requires_key(provider.id):
        return True
    return bool(Credentials(directory, [provider.key_env]).secret(provider.key_env))


# What is here.

def found(directory: Path, wait: bool = True) -> dict:
    """The sources on this computer: {"agents", "keys", "local", "chosen"}. Keys themselves
    are never in it: only which are set, and where from. Without `wait` (a page's request),
    whether each agent is signed in is what was found last (None the first time), and it is
    found again behind the request."""
    from .settings import Credentials

    credentials = Credentials(Path(directory))
    credentials.load()
    keys = []
    for provider in providers.PROVIDERS.values():
        if provider.key_env and provider.id != "custom" and os.environ.get(provider.key_env):
            kept = bool(credentials.secret(provider.key_env))
            keys.append({"kind": "key", "provider": provider.id, "name": provider.name, "key_env": provider.key_env,
                         "kept": kept, "from": "the credentials file" if kept else "the environment",
                         "model": providers.DEFAULT["model"] if provider.id == providers.DEFAULT["provider"] else ""})
    return {"agents": agent_sources(wait=wait), "keys": keys, "local": _kept("local", local_models, wait, []),
            "chosen": chosen(Path(directory))}


def chosen(directory: Path) -> dict | None:
    """The model in use: {provider, model, name: its source's name, model_name: the model's
    own, efforts: the effort levels it has}, or None."""
    from . import model_list

    try:
        entry = model_list.select(directory, native=True)
    except ValueError:
        return None
    if entry is None:
        return None
    return {"provider": entry["provider"], "model": entry["model"], "name": source_name(entry["provider"]),
            "model_name": model_name(entry), "efforts": list(entry.get("efforts") or ())}


def source_name(provider: str, given=None) -> str:
    """What a source is called: the agent's or the provider's own name; an agent of the ACP
    Registry by the name the registry gives it (`given` where the caller has it)."""
    if providers.is_agent(provider):
        known = providers.AGENTS.get(provider.removeprefix("acp:"))
        if known:
            return known.name
        return str(given or "").strip() or _agent_names().get(provider) or provider.removeprefix("acp:")
    known = providers.PROVIDERS.get(provider)
    return known.name if known else str(provider)


def _agent_names() -> dict:
    """{provider: name} of the ACP agents connected here, as their package lists them."""
    names = {}
    try:
        from .extensions import modules

        for module in modules():
            for row in getattr(module, "agents", lambda: [])():
                if row.get("kind") == "acp" and row.get("name"):
                    names[row["id"]] = str(row["name"]).removeprefix("custom/")
    except (OSError, ValueError):
        pass
    return names


def model_name(entry: dict) -> str:
    """What a model of the list is called by itself, without its source. An agent's "default"
    is the model the agent itself is set to (it was kept before its models were asked for);
    an entry once named after its source says so instead of repeating the source."""
    name, model = str(entry.get("name") or ""), str(entry.get("model") or "")
    if providers.is_agent(entry.get("provider")) and model == "default" and \
            name in ("", "default", source_name(entry["provider"]), entry["provider"]):
        return "Default"
    return name or model


# What takes a second or two to find on this computer (an agent's own status command, a model
# server that does not answer), as it was found last: {key: (when, answer)}. A page's request
# is answered from it, and it is found again behind the request once it is old.
_FOUND = {}
_FINDING = set()
FOUND_SECONDS = 60.0


def _kept(key, find, wait: bool, default=None):
    """find(), kept for FOUND_SECONDS. Without `wait`: what was found last (`default` the
    first time), found again in the background when that is old."""
    import threading

    when, answer = _FOUND.get(key, (0.0, default))
    if time.time() - when <= FOUND_SECONDS:
        return answer

    def ask():
        try:
            _FOUND[key] = (time.time(), find())
        finally:
            _FINDING.discard(key)

    if wait:
        ask()
        return _FOUND[key][1]
    if key not in _FINDING:
        _FINDING.add(key)
        threading.Thread(target=ask, name="found-here", daemon=True).start()
    return answer


def _signed_in(path: str, agent, wait: bool) -> bool | None:
    return _kept(("signed", path), lambda: signed_in(path, agent), wait)


def agent_sources(wait: bool = True) -> list[dict]:
    """The agents that can be the model: the ones people use most (providers.AGENTS), each
    with whether its command line is on this computer (`installed`; `install` is how to get
    it) and whether it is signed in, then the ACP agents the user connected (a package's
    agents()). `standalone`: it needs no command line here: choosing it installs its adapter,
    and its user signs in through it (sign_in). What can be chosen as it is comes first."""
    rows = []
    for agent in providers.AGENTS.values():
        path = shutil.which(agent.executable)
        rows.append({"kind": "agent", "provider": f"acp:{agent.id}", "name": agent.name, "plan": agent.plan,
                     "installed": path is not None, "install": agent.install, "standalone": agent.standalone,
                     "signed_in": _signed_in(path, agent, wait) if path else None, "sign_in": agent.sign_in,
                     "model": "default"})
    listed = {row["provider"] for row in rows}
    try:
        from .extensions import modules

        for module in modules():
            for row in getattr(module, "agents", lambda: [])():
                if row.get("kind") == "acp" and row.get("installed") and row["id"] not in listed:
                    listed.add(row["id"])
                    rows.append({"kind": "agent", "provider": row["id"], "name": row.get("name") or row["id"],
                                 "plan": "", "installed": True, "install": "", "standalone": True,
                                 "signed_in": None, "sign_in": "", "model": "default"})
    except (OSError, ValueError):
        pass
    return sorted(rows, key=lambda row: (not usable(row), not row["installed"]))


def usable(source: dict) -> bool:
    """Whether a source of found() can be chosen as it is: an agent whose command line is
    here and not known to be signed out, or one that needs none (its adapter installs when
    it is chosen, and it is signed in to through it); a key or a local model always."""
    if source.get("kind") != "agent":
        return True
    if source.get("installed", True):
        return source.get("signed_in") is not False
    return bool(source.get("standalone"))


def more_agents() -> list[dict]:
    """The other agents of the ACP Registry that run on this computer, as sources: choosing
    one installs its pinned adapter (prepare_agent), and it answers under its own sign-in.
    The registry is read when it never was (that takes the network)."""
    from .host import connectors

    return [{"kind": "agent", "provider": row["id"], "name": row["name"], "plan": "", "installed": True, "install": "",
             "standalone": True, "signed_in": None, "sign_in": "", "model": "default"}
            for row in connectors.agents(registry=True)
            if row["state"] == "available" and row.get("runs_here", True)
            and row["id"].removeprefix("acp:") not in providers.AGENTS]


def signed_in(path: str, agent) -> bool | None:
    """Whether the agent's own command says it is signed in (its status command ends 0);
    None when it has no such command or does not answer: trying it tells."""
    if not agent.status:
        return None
    try:
        ran = subprocess.run([path, *agent.status], capture_output=True, timeout=20, stdin=subprocess.DEVNULL,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError):
        return None
    return ran.returncode == 0


def local_models() -> list[dict]:
    """The models an Ollama on this computer has pulled."""
    try:
        with urlopen("http://127.0.0.1:11434/api/tags", timeout=0.6) as answer:
            names = [row.get("name") for row in json.load(answer).get("models") or [] if row.get("name")]
    except (OSError, ValueError):
        return []
    return [{"kind": "local", "provider": "ollama", "name": "Ollama", "model": name} for name in names]


# What a source offers.

# {(provider, model): (when, answer)}: asking an agent takes a few seconds (it is started), a
# provider's catalog a request; an answer stands this long.
_OFFERED: dict = {}
OFFERED_SECONDS = 600.0


def offered(directory: Path, provider: str, model: str | None = None, log=None) -> dict:
    """What the source `provider` offers: {"models": [{id, name, description?, efforts?,
    images?}], "current": the model it uses unless told (an agent's own setting; None for a
    provider), "efforts": the effort levels of `model` (of `current` without one)}.

    An agent is asked through ACP what it declares (it is made ready and started; no prompt
    is sent), its effort levels for the one model asked about, since they differ by model.
    A provider's catalog says each model's levels. A ValueError or a Problem says why the
    source could not be asked."""
    key = (provider, model or "")
    kept = _OFFERED.get(key)
    if kept and time.time() - kept[0] < OFFERED_SECONDS:
        return kept[1]
    if providers.is_agent(provider):
        prepare_agent(provider, log or (lambda message: None))
        answer = _declared(provider, model)
    else:
        from .settings import Credentials

        known = providers.PROVIDERS.get(provider)
        if known is not None and known.key_env:
            Credentials(Path(directory), [known.key_env]).load()
        rows = providers.catalog(Path(directory), provider)
        row = next((item for item in rows if item["id"] == model), None)
        answer = {"models": rows, "current": None, "efforts": list((row or {}).get("efforts") or ())}
    _OFFERED[key] = (time.time(), answer)
    return answer


def _declared(provider: str, model: str | None) -> dict:
    """What an ACP agent declares in a session opened for the question (its config options:
    the models, and the thought levels of the model it is on)."""
    from tempfile import TemporaryDirectory

    from .extensions import modules

    factory = None
    for module in modules():
        if getattr(module, "session_adapter", None) and any(
                agent["id"] == provider and agent["kind"] == "acp" and agent["installed"]
                for agent in getattr(module, "agents", lambda: [])()):
            factory = module.session_adapter
            break
    if factory is None:
        raise ValueError(f"{source_name(provider)} is not connected (harness agents add)")

    def values(config, category):
        option = next((item for item in config if item.get("category") == category), {})
        rows = [choice for item in option.get("options", []) for choice in item.get("options", [item])]
        return option, [row for row in rows if isinstance(row.get("value"), str) and row["value"]]

    with TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
        folder = Path(temporary)
        adapter = factory(provider, folder / "probe", cwd=folder, isolation=None, model=None, effort=None)
        try:
            adapter.open("", ())
            option, rows = values(adapter.capabilities.get("config_options") or [], "model")
            current = option.get("currentValue") if isinstance(option.get("currentValue"), str) else None
            # "default" is how a model entry says "what the agent is set to" (AcpModel sets
            # nothing then): an agent's own option of that value is one of its other models
            # under another name, and is left out.
            models = [{"id": row["value"], "name": str(row.get("name") or row["value"]),
                       **({"description": str(row["description"])} if row.get("description") else {})}
                      for row in rows if row["value"] != "default"]
            wanted = model if model and model != "default" else None
            if wanted and wanted != current:
                adapter.set_model(model=wanted)
            _, levels = values(adapter.capabilities.get("config_options") or [], "thought_level")
        except (RuntimeError, OSError) as error:
            raise ValueError(str(error)) from error
        finally:
            adapter.close()
    return {"models": models, "current": current,
            "efforts": [row["value"] for row in levels if row["value"] != "default"]}


def described(directory: Path, entry: dict, log=None) -> dict:
    """`entry` ({provider, model, base_url}) as its source describes it: the model by its
    own name with its effort levels (and whether it reads images, where the source says).
    An agent's "default" becomes the model the agent is set to, so that the list names a
    model and not the agent. Unchanged when the source cannot be asked now."""
    try:
        found = offered(directory, entry["provider"], entry["model"], log)
    except Exception:  # noqa: BLE001 - the entry works without its description
        known = providers.PROVIDERS.get(entry["provider"])
        if known is None:
            return dict(entry)
        # the provider could not be asked now: the levels its API tells apart, at least
        from .runtime.decision.model import effort_levels

        levels = effort_levels(known.backend, entry.get("base_url") or known.base_url, entry["model"])
        return {**entry, **({"efforts": levels} if levels else {})}
    model = entry["model"]
    if providers.is_agent(entry["provider"]) and model == "default" and found.get("current"):
        model = found["current"]
    row = next((item for item in found["models"] if item["id"] == model), None)
    if row is None:
        return dict(entry)
    efforts = found["efforts"] if providers.is_agent(entry["provider"]) else list(row.get("efforts") or ())
    # a gateway names a model with its maker in front ("DeepSeek: DeepSeek V4.1 Flash"): the model's own name
    maker, _, name = str(row["name"]).partition(": ")
    name = name if name and len(maker) <= 24 and "/" not in maker else str(row["name"])
    return {**entry, "model": model, "name": name, "efforts": efforts,
            **({"images": row["images"]} if isinstance(row.get("images"), bool) else {})}


# One real call.

def entry_of(choice: dict) -> dict:
    """{provider, model, base_url} of a choice, checked; the adapter's own default model
    for an agent that names none."""
    provider = str(choice.get("provider") or "")
    if providers.is_agent(provider):
        return {"provider": provider, "model": str(choice.get("model") or "default"), "base_url": None}
    return providers.check({"provider": provider, "model": choice.get("model"), "base_url": choice.get("base_url")})


def tryout(directory: Path, choice: dict, key: str | None = None, log=None) -> dict:
    """Ask the chosen model for one word, as a conversation would: {"seconds", "reply"}.
    A Problem says why it did not answer and what to do. `key` is one just typed; else
    the one found for the provider is used. Nothing is kept (choose keeps)."""
    from .runtime.decision.model import ChatModel
    from .settings import Credentials

    log = log or (lambda message: None)
    entry = entry_of(choice)
    name = source_name(entry["provider"], choice.get("name"))
    provider = providers.PROVIDERS.get(entry["provider"])
    previous = None
    if providers.is_agent(entry["provider"]):
        prepare_agent(entry["provider"], log)
    elif provider is not None and provider.key_env:
        Credentials(Path(directory), [provider.key_env]).load()
        key = (key or "").strip() or os.environ.get(provider.key_env) or ""
        if providers.requires_key(provider.id) and not key:
            raise Problem(f"{name} needs a key", "paste the key, or pick another source", code="no_key")
        previous = os.environ.get(provider.key_env)
        if key:
            os.environ[provider.key_env] = key
    role = {**providers.model_role(entry), "max_output_tokens": 256, "retries": 0, "timeout_seconds": 90.0}
    log(f"asking {name} for one word")
    started = time.monotonic()
    model = None
    try:
        model = ChatModel(role)
        reply = model.complete(TRY_SYSTEM, TRY_MESSAGE)
    except Problem:
        raise
    except Exception as error:  # noqa: BLE001 - whatever the transport raised is explained
        raise refused(entry, name, error) from None
    finally:
        if model is not None:
            try:
                model.close()
            except Exception:  # noqa: BLE001 - the answer, or its failure, is what counts
                pass
        if provider is not None and provider.key_env:
            # As it was: a key that was only tried stays nowhere (choose keeps one that works).
            if previous is None:
                os.environ.pop(provider.key_env, None)
            else:
                os.environ[provider.key_env] = previous
    return {"seconds": round(time.monotonic() - started, 1), "reply": (reply.text or "").strip()[:80]}


def prepare_agent(provider: str, log) -> None:
    """Have what an ACP agent as the model needs: the package that speaks ACP (installed on
    first use, as packages.auto_install says) and the agent's adapter from the ACP Registry."""
    from .extensions import first, require

    identifier = provider.removeprefix("acp:")
    known = providers.AGENTS.get(identifier)
    if known is not None and not known.standalone and shutil.which(known.executable) is None:
        # its adapter goes through the agent's own command line and sign-in on this computer
        raise Problem(f"{known.name} is not installed on this computer", known.setup, code="agent_missing")
    if first("model_backend") is None:
        log("installing the package that connects agents (external-agents)")
    try:
        require("model_backend", "commands", "agents")
        ready = first("agent_ready")
        if ready is None:
            # The package is one from before an agent could be the model: it would be started
            # without its adapter, and say something of its own that helps nobody.
            raise Problem("the package that connects agents (external-agents) is older than this version of "
                          "The Harness", "harness install --update external-agents, then start The Harness again",
                          code="package_old")
        ready(provider, log)
    except Problem:
        raise
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        raise Problem(f"{source_name(provider)} could not be connected: {error}",
                      "harness agents list shows the agents here, harness agents list --registry the ones that can be added", code="agent_unavailable") from None


def refused(entry: dict, name: str, error: Exception) -> Problem:
    """Why the try did not answer, with what to do: told apart by what the provider or the
    agent said."""
    text = " ".join(str(error).split())
    low = text.lower()
    if providers.is_agent(entry["provider"]):
        known = providers.AGENTS.get(entry["provider"].removeprefix("acp:"))
        if any(word in low for word in ("auth", "log in", "login", "sign in", "signed in", "credential", "401")):
            # one whose command line is here is signed in to with that; any other through the agent itself
            here = known is not None and shutil.which(known.executable) is not None
            return Problem(f"{name} is not signed in",
                           (known.sign_in if here else
                            f"sign in to it (harness agents login {entry['provider'].removeprefix('acp:')})") + ", then try again",
                           code="not_signed_in")
        if any(word in low for word in ("limit", "quota", "429", "usage")):
            return Problem(f"{name} has reached its plan's limit ({text[:200]})",
                           "wait until it resets, or pick another source", code="plan_limit")
        return Problem(f"{name} did not answer: {text[:300]}",
                       "run it once by itself to see that it works, then try again", code="agent_failed")
    if "http 401" in low or "http 403" in low or "unauthorized" in low or "invalid api key" in low:
        return Problem(f"{name} refused the key", "check that the key is complete and belongs to this provider",
                       code="key_refused")
    if "http 402" in low or "insufficient" in low or "credit" in low or "balance" in low:
        return Problem(f"{name} says the account has no credit left", "add credit, or pick another source",
                       code="no_credit")
    if "http 404" in low or "not a valid model" in low or "no endpoints" in low or "model_not_found" in low:
        return Problem(f"{name} has no model called {entry['model']}", "pick a model from its list", code="no_model")
    if "http 429" in low:
        return Problem(f"{name} is limiting requests right now", "try again in a minute", code="rate_limited")
    if "request failed" in low or "timed out" in low or "connection" in low or "getaddrinfo" in low:
        where = entry.get("base_url") or (providers.PROVIDERS[entry["provider"]].base_url
                                         if entry["provider"] in providers.PROVIDERS else "") or name
        return Problem(f"no connection to {where}", "check the network (and the address, for an endpoint of your own)",
                       code="network")
    return Problem(f"{name} did not answer: {text[:300]}", "check the model name and the key", code="model_failed")


# Signing in to an agent through the agent itself.

def sign_in(provider: str, method: str | None = None, log=None):
    """Sign in to the agent `provider` through the ways it offers over ACP, as Zed shows an
    agent's authentication methods: no command line of it is needed here, and nothing of the
    sign-in is read or kept (the agent keeps its own). Without `method`: the ways,
    [{id, name, description}] ([] when it offers none: it is signed in to with its own
    command). With `method`: that one now; the agent opens what it needs (a page in the
    browser) and this returns when its user is through: {"signed_in": True, "method"}.
    A Problem says why it could not be done."""
    from .extensions import first

    name = source_name(provider)
    prepare_agent(provider, log or (lambda message: None))
    hook = first("agent_sign_in")
    if hook is None:
        if method is None:
            return []
        raise Problem("the package that connects agents (external-agents) is older than this version of The Harness",
                      "harness install --update external-agents, then start The Harness again", code="package_old")
    try:
        return hook(provider, method)
    except Problem:
        raise
    except (ValueError, RuntimeError, OSError, TimeoutError) as error:
        raise Problem(f"{name} was not signed in to: {error}",
                      "start the sign-in again and go through the page it opens, or sign in with the agent's own command",
                      code="sign_in_failed") from None
    finally:
        if method is not None:  # what it offers is asked again once it is signed in to
            for key in [key for key in _OFFERED if key[0] == provider]:
                _OFFERED.pop(key, None)


def sign_in_offer(provider, problem) -> dict:
    """{"sign_in": the ways an agent that answered "not signed in" offers to sign in through
    it}, for a frontend to offer in place; {} for any other failure, or when it offers none."""
    if getattr(problem, "code", None) != "not_signed_in" or not providers.is_agent(provider):
        return {}
    try:
        ways = sign_in(provider)
    except Exception:  # noqa: BLE001 - the failure is told without the offer
        return {}
    return {"sign_in": ways} if ways else {}


# Keeping it.

def choose(directory: Path, choice: dict, key: str | None = None, log=None) -> dict:
    """Make the choice the model in use: its entry in the model list (enabled), [model] of
    config.toml, and its key in the credentials file (a key typed now, or the one found in
    the environment). The entry is kept as its source describes the model (described): by
    the model's name, with its effort levels; an agent chosen without a model keeps the one
    it is set to. Returns the entry."""
    from . import model_list
    from .settings import Credentials

    directory = Path(directory)
    entry = entry_of(choice)
    provider = providers.PROVIDERS.get(entry["provider"])
    if provider is not None and provider.key_env:
        credentials = Credentials(directory, [provider.key_env])
        credentials.load()
        value = (key or "").strip() or os.environ.get(provider.key_env) or ""
        if value and credentials.secret(provider.key_env) != value:
            credentials.save(value, provider.key_env)
    kept = described(directory, entry, log)
    saved = model_list.models(directory, {"action": "save", **kept})
    entry = {name: kept[name] for name in ("provider", "model", "base_url")}
    wanted = model_list.entry(entry)["id"]
    if any(row["id"] == wanted and not row.get("enabled", True) for row in saved):
        model_list.models(directory, {"action": "enable", "id": wanted, "enabled": True})
    providers.save(directory, entry)
    return next(row for row in saved if row["id"] == wanted)


def next_steps() -> list[str]:
    """What is shown right after the first run: where the commands are, as Claude Code's
    first screen does, and nothing that explains the product."""
    return ["/help for commands · /model to change the model"]
