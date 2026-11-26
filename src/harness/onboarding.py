"""The first run, the same in every frontend: what on this computer can be the agent's
model (found), one real call with the chosen one (tryout), and keeping it (choose).

A model comes from one of three kinds of source, and any of them alone is enough:

- an agent's command line that is installed and signed in here (Claude Code, Codex, any
  agent that speaks the Agent Client Protocol): it runs under the user's own plan, through
  ACP; its sign-in stays its own, nothing of it is read or kept here;
- a provider's API key (found in the environment or in the credentials, or typed);
- a model that runs on this computer.

Only what is found here or what the user adds is listed; nothing is chosen for the user and
no other vendor's tool is installed. A key that works is kept in the credentials file even
when it came from the environment: a session host started at login does not see the
variables of the user's shell.

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

def found(directory: Path) -> dict:
    """The sources on this computer: {"agents", "keys", "local", "chosen"}. Keys themselves
    are never in it: only which are set, and where from."""
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
    return {"agents": agent_sources(), "keys": keys, "local": local_models(), "chosen": chosen(Path(directory))}


def chosen(directory: Path) -> dict | None:
    """The model in use ({provider, model, name}), or None."""
    from . import model_list

    try:
        entry = model_list.select(directory, native=True)
    except ValueError:
        return None
    if entry is None:
        return None
    return {"provider": entry["provider"], "model": entry["model"], "name": source_name(entry["provider"])}


def source_name(provider: str) -> str:
    if providers.is_agent(provider):
        known = providers.AGENTS.get(provider.removeprefix("acp:"))
        return known.name if known else provider.removeprefix("acp:")
    known = providers.PROVIDERS.get(provider)
    return known.name if known else str(provider)


def agent_sources() -> list[dict]:
    """The agents' command lines installed here (providers.AGENTS that are on the PATH,
    with whether they are signed in), then the ACP agents the user installed or configured
    (a package's agents())."""
    rows = []
    for agent in providers.AGENTS.values():
        path = shutil.which(agent.executable)
        if path is None:
            continue
        rows.append({"kind": "agent", "provider": f"acp:{agent.id}", "name": agent.name, "plan": agent.plan,
                     "signed_in": signed_in(path, agent), "sign_in": agent.sign_in, "model": "default"})
    listed = {row["provider"] for row in rows}
    try:
        from .extensions import modules

        for module in modules():
            for row in getattr(module, "agents", lambda: [])():
                if row.get("kind") == "acp" and row.get("installed") and row["id"] not in listed:
                    listed.add(row["id"])
                    rows.append({"kind": "agent", "provider": row["id"], "name": row.get("name") or row["id"],
                                 "plan": "", "signed_in": None, "sign_in": "", "model": "default"})
    except (OSError, ValueError):
        pass
    return rows


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
    name = source_name(entry["provider"])
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
    if known is not None and shutil.which(known.executable) is None:
        raise Problem(f"{known.name} is not installed on this computer", known.install, code="agent_missing")
    if first("model_backend") is None:
        log("installing the package that connects agents (external-agents)")
    try:
        require("model_backend", "commands", "agents")
        ready = first("agent_ready")
        if ready is not None:
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
            return Problem(f"{name} is not signed in ({text[:200]})",
                           (known.sign_in if known else "sign in with the agent's own command") + ", then try again",
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


# Keeping it.

def choose(directory: Path, choice: dict, key: str | None = None) -> dict:
    """Make the choice the model in use: its entry in the model list (enabled), [model] of
    config.toml, and its key in the credentials file (a key typed now, or the one found in
    the environment). Returns the entry."""
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
    named = {"name": source_name(entry["provider"])} if providers.is_agent(entry["provider"]) and         entry["model"] == "default" else {}
    saved = model_list.models(directory, {"action": "save", **entry, **named})
    wanted = model_list.entry(entry)["id"]
    if any(row["id"] == wanted and not row.get("enabled", True) for row in saved):
        model_list.models(directory, {"action": "enable", "id": wanted, "enabled": True})
    providers.save(directory, entry)
    return entry


def next_steps() -> list[str]:
    """What to do right after the first run: things to say, and the commands used most."""
    return ["Say what you want done, in your own words. For example:",
            "  what can you do on this computer?",
            "  look at this folder and tell me what is in it",
            "/help lists the commands, /model changes the model, harness setup runs this again."]
