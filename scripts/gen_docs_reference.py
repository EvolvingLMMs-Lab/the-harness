#!/usr/bin/env python3
"""The documentation's reference pages, generated from the code at build time.

`deno task build` and `deno task dev` (docs/deno.json) run this file with `--write` first;
it writes these pages into the site's content (docs/src/content/docs/), where git ignores them:

    reference/cli.md                 the CLI, from its argument parser
    reference/configuration.md       configuration keys, from the dictionaries the validators use
    reference/skills/<name>.md       each skill of the core: manifest, functions (docstrings), what the
                                     model reads (a package's skills are on its page under /packages/)
    reference/agent.md               the agent resolved: skills, services, identity
    reference/configs.md             models, experiments and deploys
    reference/environment.md         the environments' shared pins (environment/README.md)
    reference/api/<module>.md        the Python API, from docstrings

It also renders the tables README.md embeds between `<!-- generated: NAME -->` markers:

    python scripts/gen_docs_reference.py --readme     rewrite them
    python scripts/gen_docs_reference.py --write      write the pages into the site's content
    python scripts/gen_docs_reference.py --list       print the pages it generates

Standard library and the harness's own (standard-library) modules only; nothing is
started and no model is called.
"""

import argparse
import ast
import inspect
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tomllib

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]

# The core's own content (harness.paths.ROOT).
BUILTIN = ROOT / "src" / "harness" / "builtin"
CONTENT = ROOT / "docs" / "src" / "content" / "docs"
PACK = ROOT / "packages" / "workspace" / "prompts" / "workspace"


def _cell(text) -> str:
    """A table cell: pipes escaped, and <...> outside code spans shown, not taken as HTML."""
    parts = str(text).replace("\n", " ").split("`")
    parts = [part if index % 2 else part.replace("<", "&lt;").replace(">", "&gt;")
             for index, part in enumerate(parts)]
    return "`".join(parts).replace("|", "\\|")


def _table(header, rows) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(_cell(value) for value in row) + " |" for row in rows]
    return "\n".join(lines) + "\n"


def _facts(rows) -> str:
    """(label, value) pairs as a list: **label**: value."""
    return "\n".join(f"- **{label}**: {_cell(value)}" for label, value in rows) + "\n"


def _keys(mapping) -> str:
    return _table(["Key", "Meaning"], [(f"`{key}`", value) for key, value in mapping.items()])


# -- CLI ------------------------------------------------------------------------------

def _subcommands(parser):
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            helps = {choice.dest: choice.help for choice in action._choices_actions}
            # The core's commands: a package's own are on its page under /packages/.
            return [(name, sub, helps.get(name, "")) for name, sub in action.choices.items()
                    if not sub.get_default("package_command")]
    return []


def _arguments(parser):
    rows = []
    for action in parser._actions:
        if isinstance(action, (argparse._HelpAction, argparse._SubParsersAction)):
            continue
        name = ", ".join(f"`{flag}`" for flag in action.option_strings) or f"`{action.metavar or action.dest}`"
        default = action.default
        if isinstance(default, Path):
            default = default.as_posix()
        shown = "" if default in (None, False, [], argparse.SUPPRESS) or action.option_strings == [] else f"`{default}`"
        rows.append((name, shown, action.help or ""))
    return rows


def cli_page() -> str:
    os.environ["COLUMNS"] = "100"
    from harness.cli import parser

    # The core's commands; an installed package adds its own (its README says what they are).
    root = parser(packages=False)
    out = ["# CLI\n", "`harness` (or `python scripts/harness` from a checkout). Every command prints JSON or a "
           "table; errors go to stderr as `{\"error\": ...}` with exit status 1. An installed package adds "
           "its own commands to `harness --help`.\n"]
    out.append(_table(["Command", "What it does"], [(f"[`{name}`](#harness-{name})", text)
                                                    for name, _, text in _subcommands(root)]))
    for name, sub, text in _subcommands(root):
        out += [f"\n## harness {name}\n", f"{text}\n" if text else "", "```text\n" + sub.format_usage() + "```\n"]
        rows = _arguments(sub)
        if rows:
            out.append(_table(["Argument", "Default", "Meaning"], rows))
        if sub.epilog:
            out.append(f"{sub.epilog}\n")
        for nested, subsub, subtext in _subcommands(sub):
            out += [f"\n### harness {name} {nested}\n", f"{subtext}\n", "```text\n" + subsub.format_usage() + "```\n",
                    _table(["Argument", "Default", "Meaning"], _arguments(subsub))]
    return "\n".join(part for part in out if part)


# -- configuration keys ----------------------------------------------------------------

PACK_KEYS = {
    "sections": "the files of the pack in order: { file, skills = [...] (included when one is enabled), "
                "optional = true (may be missing) }",
    "undocumented": "exported names the pack does not describe (the documentation check skips them)",
}


def configuration_page() -> str:
    from harness.bench import BENCH_KEYS, bench_names, bench_specs
    from harness_eval.bench import BENCHMARK_KEYS, benchmark
    from harness.config.agent import AGENT_KEYS, ROLE_DOCS, RUNTIME_KEYS
    from harness_eval.experiments import EXPERIMENT_KEYS
    from harness.runtime.decision.model import MODEL_KEYS
    from harness.runtime.decision.prompts import FEATURES
    from harness.runtime.execution.skills import SKILL_KEYS
    from harness_local_models.deploy import DEPLOY_KEYS, PLACEMENT_KEYS
    from harness.packages.environments import ENVIRONMENT_KEYS, SOURCE_KEYS
    from harness.services.registry import MANIFEST_KEYS

    benches = []
    for name in bench_names():
        spec = bench_specs()[name]
        run = benchmark(spec)
        benches += [f"### {name}\n", f"{spec.summary}. Kind `{spec.kind}`"
                    + (f", embodiment `{spec.embodiment}`" if spec.embodiment else "") + f". Tasks: {run.tasks}.\n"]
        if spec.worker:
            benches += ["Experiment `[worker]`:\n", _keys(spec.worker)]
        if run.deploy:
            benches += [f"Deploy `[benches.{name}]`:\n", _keys(run.deploy)]
    return "\n".join([
        "# Configuration keys\n",
        "Generated from the dictionaries the validators use: a key not listed here is an error in its file "
        "(except under `[runtime]`, which is open). Paths are relative to the file that names them; files "
        "may `include` others ([Configuration](/docs/configure/configuration/)).\n",
        "## The agent\n", "`configs/default.toml`, and any agent file that includes it\n", _keys(AGENT_KEYS),
        "`[skills]`: `layers = { learned, reactive, handlers }` (defaults false, true, true), or "
        "`names = [...]`; `disable = [...]` removes skills. `[services]`: `segmenter = \"sam3\"`, "
        "`policies = [...]`, `world_models = [...]`; each a service name, or `{ service = \"...\", ... }` with "
        "client keys on top. `[budget]`: `max_model_calls`.\n",
        "## Models\n", "`configs/models/<name>.toml`: one table per role, plus `[runtime]` (settings the "
        "model needs, merged into the agent's) and `description`.\n",
        _table(["Role", "What for"], [(f"`[{role}]`", text) for role, text in ROLE_DOCS.items()]),
        "### Keys of a role\n", _keys(MODEL_KEYS),
        "## Runtime\n", "`[runtime]` of the agent (or of a model file, or an experiment's overrides). Some keys are "
        "written by the resolution itself.\n", _keys(dict(sorted(RUNTIME_KEYS.items()))),
        "## Experiments\n", "`configs/experiments/<name>.toml`\n", _keys(EXPERIMENT_KEYS),
        "## Deploys\n", "`configs/deploy/<machine>.toml`\n", _keys(DEPLOY_KEYS),
        "### Placement of a service\n", "`[services.<name>]` of a deploy.\n", _keys(PLACEMENT_KEYS),
        "## Service manifests\n", "`services/<name>.toml`\n", _keys(MANIFEST_KEYS),
        "### Environments\n", "`[environment]` of a service manifest or a bench: the environment it runs in, "
        "installed the first time a run needs it under `~/.cache/harness/envs/<name>/<hash>/` "
        "([Services](/docs/configure/services/)).\n", _keys(ENVIRONMENT_KEYS),
        "### Sources\n", "One entry of an environment's `sources`: a checkout at a fixed commit, shared under "
        "`~/.cache/harness/sources/`.\n", _keys(SOURCE_KEYS),
        "## Skills\n", "`skills/<name>/skill.toml`\n", _keys(SKILL_KEYS),
        "## Benches\n", "`benches/<name>/bench.toml` (harness.bench), and what each bench takes\n",
        _keys(BENCH_KEYS), "### Run as a benchmark\n", "The keys of bench.toml the eval package reads "
        "(harness_eval.bench): what running a bench as a benchmark takes\n", _keys(BENCHMARK_KEYS), *benches,
        "## Prompt packs\n", "`prompts/<pack>/pack.toml`. Text inside a section is kept only when every skill or "
        "feature an `<!-- if: a, b -->` marker names is enabled (`<!-- else -->`, `<!-- end -->`; markers nest). "
        f"Features: {', '.join(f'`{name}`' for name in FEATURES)}.\n", _keys(PACK_KEYS),
    ])


# -- skills ------------------------------------------------------------------------------

def _full_prompt(skill=None):
    """Core skill documentation in the public workspace prompt."""
    from harness.runtime.decision.prompts import FEATURES, assemble_prompt
    from harness.runtime.execution.skills import SKILLS_ROOT, load_skills
    skills = list(load_skills(SKILLS_ROOT, user=False))
    return assemble_prompt(PACK, skills, features=FEATURES)


def _api_entry(prompt: str, name: str) -> str:
    """The lines of the prompt that document `name(...)`: its line and the deeper-indented
    lines after it."""
    lines = prompt.splitlines()
    for index, line in enumerate(lines):
        stripped = line.lstrip()
        if stripped.startswith(f"{name}(") or stripped.startswith(f"{name} "):
            indent = len(line) - len(stripped)
            block = [line]
            for follow in lines[index + 1:]:
                if follow.strip() and len(follow) - len(follow.lstrip()) > indent + 1:
                    block.append(follow)
                else:
                    break
            return "\n".join(block)
    return ""


def _methods(skill) -> set:
    import ast

    module, _, cls = skill.mixin.partition(":")
    source = BUILTIN / (module.replace(".", "/") + ".py")
    if not source.exists():
        source = BUILTIN / module.replace(".", "/") / "__init__.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == cls:
            return {item.name for item in node.body if isinstance(item, ast.FunctionDef)}
    return set()


def _needs(skill) -> str:
    parts = []
    if skill.needs:
        parts.append(", ".join(skill.needs))
    if skill.needs_any:
        parts.append("one of " + ", ".join(skill.needs_any))
    return "; ".join(parts) or "–"


def skills_table(link_prefix=None) -> str:
    from harness.runtime.execution.skills import SKILLS_ROOT, load_skills

    rows = []
    for skill in load_skills(SKILLS_ROOT, user=False).values():
        name = f"[{skill.name}]({link_prefix}{skill.name}/)" if link_prefix is not None else skill.name
        rows.append((name, skill.layer, ", ".join(f"`{e}`" for e in skill.public), _needs(skill)))
    return _table(["Skill", "Layer", "Exports", "Needs"], rows)


def skill_pages() -> dict:
    from harness.runtime.execution.skills import SKILLS_ROOT, load_skills

    prompt = _full_prompt()
    pages = {"reference/skills/index.md": "\n".join([
        "# Skills\n",
        "What a model's programs can call. The agent turns skills on by interface layer or by name; a skill "
        "whose services are missing drops out, and the prompt drops its text with it "
        "([Write a skill](/docs/extend/skills/)).\n",
        skills_table(link_prefix="/docs/reference/skills/"),
    ])}
    for skill in load_skills(SKILLS_ROOT, user=False).values():
        methods = _methods(skill)
        module, _, cls = skill.mixin.partition(":")
        facts = [("Layer", skill.layer + (" (optional: only where a configuration enables it)" if skill.optional
                                            else "")), ("Needs", _needs(skill)),
                 ("Requires", ", ".join(skill.requires) or "–"),
                 ("Conflicts with", ", ".join(skill.conflicts) or "–"),
                 ("Never dropped", "yes" if skill.required else "no"), ("Mixin", f"`{skill.mixin}`"),
                 ("Manifest", f"`skills/{skill.name}/skill.toml`")]
        out = [f"# {skill.name}\n", f"{skill.summary}\n", _facts(facts)]
        out.append("## Functions\n")
        others = []
        for name in skill.public:
            # A skill whose names clash with another's prefixes its methods (exports(session) maps them).
            method = name if name in methods else f"{skill.name}_{name}" if f"{skill.name}_{name}" in methods else None
            if method is not None:
                out.append(_api_object(f"{module}.{cls}.{method}", level=3))
            else:
                others.append(name)
        if others:
            out.append("Also in the namespace: " + ", ".join(f"`{name}`" for name in others)
                       + " (constants and names the skill's `exports(session)` provides).\n")
        own = _full_prompt(skill) if skill.optional else prompt
        entries = [(name, _api_entry(own, name)) for name in skill.public]
        entries = [(name, text) for name, text in entries if text]
        if entries:
            out.append("## What the model reads\n")
            out.append("From the workspace prompt pack, with the core skills enabled:\n")
            out.append("```text\n" + "\n".join(text for _, text in entries) + "\n```\n")
        pages[f"reference/skills/{skill.name}.md"] = "\n".join(out)
    return pages


# -- services ----------------------------------------------------------------------------

def _users():
    """The services the agent names, and skills that need each kind."""
    from harness.config import load_layered
    from harness.config.agent import load_model
    from harness.runtime.execution.skills import load_skills

    systems = {}
    for path in _agent_files():
        tree = load_layered(path)
        services = tree.get("services", {})
        names = []
        for key in ("segmenter",):
            if services.get(key):
                entry = services[key]
                names.append(entry if isinstance(entry, str) else entry["service"])
        for key in ("policies", "world_models"):
            names += [entry if isinstance(entry, str) else entry["service"] for entry in services.get(key, [])]
        roles = load_model(tree.get("model")) if tree.get("model") else {}
        names += [spec["service"] for spec in roles.values() if isinstance(spec, dict) and "service" in spec]
        for name in names:
            systems.setdefault(name, []).append(path.stem)
    kinds = {}
    for skill in load_skills().values():
        for kind in (*skill.needs, *skill.needs_any):
            kinds.setdefault(kind, []).append(skill.name)
    return systems, kinds


def services_table(link_prefix=None) -> str:
    from harness.services.registry import load_services

    rows = []
    for spec in load_services().values():
        name = f"[{spec.name}]({link_prefix}{spec.name}/)" if link_prefix is not None else spec.name
        rows.append((name, spec.kind, spec.summary, f"{spec.vram_gb:g} GB" if spec.vram_gb else "–"))
    return _table(["Service", "Kind", "What it is", "VRAM"], rows)


def service_pages() -> dict:
    from harness.services.registry import load_services

    systems, kinds = _users()
    pages = {"reference/services/index.md": "\n".join([
        "# Services\n",
        "The model processes skills and model roles call; a deploy says where each runs "
        "([Services](/docs/configure/services/)). VRAM is measured on a 24 GB GPU.\n",
        services_table(link_prefix="/docs/reference/services/"),
    ])}
    for spec in load_services().values():
        facts = [("Kind", spec.kind), ("Protocol", spec.protocol), ("Default port", spec.port),
                 ("VRAM", f"{spec.vram_gb:g} GB"), ("Load time", f"about {spec.load_seconds:g} s"),
                 ("Skills that use a " + spec.kind, ", ".join(kinds.get(spec.kind, [])) or "–"),
                 ("Used by the agent", "yes" if spec.name in systems else "no")]
        out = [f"# {spec.name}\n", f"{spec.summary}\n", _facts(facts)]
        description = (spec.client or {}).get("description")
        if description:
            out += ["## What the model is told\n", f"> {description}\n"]
        if spec.weights:
            rows = []
            for entry in spec.weights:
                source = next(key for key in ("modelscope_model", "modelscope_dataset", "hf_model", "hf_dataset",
                                              "local") if key in entry)
                rows.append((f"`<weights>/{entry['dir']}`", source, entry[source] + (
                    f" (`{entry['root']}`)" if entry.get("root") else "")))
            out += ["## Weights\n", f"Downloaded with its environment (`harness install {spec.name}`).\n",
                    _table(["Directory", "Source", "From"], rows)]
        if isinstance(spec.environment, str):
            out += ["## Environment\n", f"The environment of `{spec.environment}`, shared.\n"]
        elif spec.environment:
            out += ["## Environment\n", f"Its own: Python {spec.environment['python']}, installed the first time a "
                    f"run uses it (`harness install {spec.name}`).\n"]
        if spec.notes:
            out += ["## Notes\n", f"{spec.notes}\n"]
        out += ["## Manifest\n", f"```toml\n--8<-- \"services/{spec.name}.toml\"\n```\n"]
        pages[f"reference/services/{spec.name}.md"] = "\n".join(out)
    return pages


# -- the agent, models, experiments, deploys -------------------------------------------------

def _service_names(value) -> str:
    """A [services] entry by name: "sam3", {service = "sam3", ...} or a list of them."""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return value.get("service", "")
    return ", ".join(_service_names(item) for item in value if item)


def _agent_files() -> list:
    """configs/default.toml."""
    return [BUILTIN / "configs" / "default.toml"]


def agent_page() -> str:
    """Document declared defaults without inventing a benchmark or workspace binding."""
    from harness import __version__
    path = BUILTIN / "configs" / "default.toml"
    return (f"# Task defaults\n\nCore version {__version__}. These are the declared defaults. "
            "A task's workspace provider supplies its embodiment, prompt and environment settings. "
            "The run manifest records the resulting configuration and identity.\n\n"
            + _file_block(path.relative_to(ROOT).as_posix()))


def _files(directory, title, intro, skip=(), paths=None) -> list:
    from harness.config import read_toml

    out = [f"## {title}\n", intro + "\n"]
    if paths is None:
        paths = [path for path in sorted((BUILTIN / "configs" / directory).glob("*.toml")) if path.stem not in skip]
    rows = [(f"`{path.stem}`", read_toml(path).get("description", _first_comment(path))) for path in paths]
    out.append(_table(["File", "What it is"], rows))
    for path in paths:
        out.append(_file_block(path.relative_to(ROOT).as_posix()))
    return out


def _first_comment(path) -> str:
    lines = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("#"):
            break
        lines.append(line.lstrip("# ").strip())
    return " ".join(lines)


def configs_page() -> str:
    out = ["# Models, experiments and deploys\n", "The files under `configs/` besides the agent.\n"]
    out += _files("models", "Models", "Model roles: `configs/models/<name>.toml`; `--model NAME` picks one.")
    # Experiments come with the benchmark packages; the core has the app's conversations.
    out += _files("", "Experiments", "The agent with a model on a bench: `configs/experiments/<name>.toml`, which the "
                  "benchmark packages bring (the eval package runs them). The app's conversations are the agent as "
                  "`configs/assistant.toml` changes it.", paths=[BUILTIN / "configs" / "assistant.toml"])
    out += _files("deploy", "Deploys", "Where services run on one machine: `configs/deploy/<machine>.toml`.")
    out += _files("workers", "Worker options", "Options for `harness serve --options` (a worker started by hand).")
    return "\n".join(out)


# -- embodiments ---------------------------------------------------------------------------

def _channels(channels: dict) -> str:
    """A game's channels: each with its keys and buttons, else how it uses the pointer."""
    named = []
    for name, channel in channels.items():
        held = " ".join(channel.get("keys", []) + channel.get("buttons", []))
        named.append(f"{name} ({held or channel.get('pointer', '')})")
    return ", ".join(named)


def _shield_table(value: dict) -> str:
    if all(isinstance(item, str) for item in value.values()):
        return " ".join(value)
    return " ".join(f"{key} {item}" for key, item in value.items())


def embodiments_page() -> str:
    from harness.embodiments import EMBODIMENTS_ROOT, embodiment_kind, load_embodiment

    out = ["# Embodiments\n",
           "`embodiments/<name>/embodiment.toml`: what a policy may know about a robot or a computer without "
           "asking a simulator or a VM. Workers report the same facts live; the XPolicyLab connector and "
           "workers under an observation contract take them from here.\n"]
    for path in sorted(EMBODIMENTS_ROOT.glob("*/embodiment.toml")):
        data = load_embodiment(path.parent.name)
        # A table of the shield as its keys (a game's blocked keys: the reasons are long) or
        # its settings (a game's fairness caps).
        shield = ("Shield", ", ".join(f"{key} {_shield_table(value) if isinstance(value, dict) else value}"
                                      for key, value in data.get("shield", {}).items()))
        if embodiment_kind(data) != "robot":
            # Another kind's file: its facts as they are (a computer's screen, a game's actions).
            facts = [("Kind", embodiment_kind(data)), ("Steps", f"{data['control_hz']:g} per second"),
                     *((key.replace("_", " ").capitalize(), " x ".join(map(str, value)) if isinstance(value, list)
                        else str(value)) for key, value in data.items()
                       if key not in ("name", "kind", "control_hz", "shield") and not isinstance(value, dict)),
                     *((("Channels", _channels(data["channels"])),) if data.get("channels") else ()),
                     shield]
            out += [f"## {data['name']}\n", _facts(facts),
                    f"??? note \"embodiments/{path.parent.name}/embodiment.toml\"\n\n    ```toml\n    --8<-- "
                    f"\"embodiments/{path.parent.name}/embodiment.toml\"\n    ```\n"]
            continue
        groups = ", ".join(f"{name} (joints {group['joints'][0]}-{group['joints'][-1]}, gripper {group['gripper']})"
                           for name, group in data["groups"].items())
        cameras = ", ".join(data["cameras"])
        facts = [("Robot", data.get("robot", "")), ("Control rate", f"{data['control_hz']:g} Hz"),
                 ("Joint groups", groups), ("Cameras", cameras),
                 ("Fingertip offset", f"{data.get('tip_offset_m', '–')} m along link6 +x"),
                 ("Empty closed gripper reads", data.get("gripper_empty_opening", "–")),
                 ("Table top", f"z = {data.get('table_z', '–')} m"),
                 ("Arms back to the start pose after finish", "yes" if data.get("return_to_start") else "no"),
                 shield]
        out += [f"## {data['name']}\n", _facts(facts),
                _file_block(f"embodiments/{path.parent.name}/embodiment.toml")]
    return "\n".join(out)


# -- Python API, read from the source (static: nothing is imported) -----------------------------

def _source(dotted: str):
    """(module path, the rest) for a dotted name: the longest prefix that is a file under src/ or
    the repository root."""
    parts = dotted.split(".")
    for cut in range(len(parts), 0, -1):
        base = Path(*parts[:cut])
        from harness.paths import package_roots

        for root in (ROOT / "src", BUILTIN, ROOT, *package_roots()):
            for candidate in (root / base.with_suffix(".py"), root / base / "__init__.py"):
                if candidate.exists():
                    return candidate, parts[cut:]
    raise LookupError(f"no source for {dotted}")


def _text(docstring) -> str:
    """A docstring as Markdown: Google-style sections (Args:, Returns:, ...) become a bold
    label and a list, and <...> outside code spans is shown, not taken as HTML."""
    if not docstring:
        return ""
    out, section = [], False
    for line in inspect.cleandoc(docstring).splitlines():
        header = re.match(r"^(Args|Arguments|Returns|Yields|Raises|Attributes|Example|Examples|Note|Notes):$", line)
        if header:
            out += ["", f"**{header.group(1)}**", ""]
            section = True
            continue
        if section and line.startswith("    "):
            entry = re.match(r"^    (\*{0,2}[A-Za-z_][\w.]*)(?: \(([^)]*)\))?:\s*(.*)$", line)
            if entry and not line.startswith("     "):
                name, kind, rest = entry.groups()
                out.append(f"- `{name}`" + (f" ({kind})" if kind else "") + (f": {rest}" if rest else ""))
            else:
                out[-1] += " " + line.strip()
            continue
        if line.strip():
            section = False
        out.append(line)
    text = "\n".join(out).strip()
    parts = text.split("`")
    return "`".join(part if index % 2 else part.replace("<", "&lt;").replace(">", "&gt;")
                    for index, part in enumerate(parts)) + "\n"


def _signature(node, method=False) -> str:
    args = node.args
    if method and args.posonlyargs + args.args and (args.posonlyargs + args.args)[0].arg in ("self", "cls"):
        args = ast.arguments(posonlyargs=args.posonlyargs[1:] if args.posonlyargs else [],
                             args=args.args if args.posonlyargs else args.args[1:], vararg=args.vararg,
                             kwonlyargs=args.kwonlyargs, kw_defaults=args.kw_defaults, kwarg=args.kwarg,
                             defaults=args.defaults)
    returns = f" -> {ast.unparse(node.returns)}" if node.returns else ""
    prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
    return f"{prefix} {node.name}({ast.unparse(args)}){returns}"


def _function(node, level, method=False) -> str:
    return "\n".join([f"{'#' * level} `{node.name}`\n", f"```python\n{_signature(node, method)}\n```\n",
                      _text(ast.get_docstring(node))])


def _class(node, level) -> str:
    bases = ", ".join(ast.unparse(base) for base in node.bases)
    init = next((item for item in node.body if isinstance(item, ast.FunctionDef) and item.name == "__init__"), None)
    signature = f"class {node.name}" + (f"({bases})" if bases else "")
    if init is not None:
        signature += "\n    " + _signature(init, method=True).replace("def __init__", "__init__")
    out = [f"{'#' * level} `{node.name}`\n", f"```python\n{signature}\n```\n", _text(ast.get_docstring(node))]
    for item in node.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and not item.name.startswith("_"):
            out.append(_function(item, level + 1, method=True))
    return "\n".join(out)


def _api_object(dotted: str, level: int) -> str:
    """One function, class or method, found by its dotted name."""
    path, rest = _source(dotted)
    nodes = ast.parse(path.read_text(encoding="utf-8")).body
    node = None
    for name in rest:
        node = next(item for item in nodes if isinstance(item, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
                    and item.name == name)
        nodes = getattr(node, "body", [])
    if isinstance(node, ast.ClassDef):
        return _class(node, level)
    return _function(node, level, method=len(rest) > 1)


def _api_module(module: str) -> str:
    """A module: its docstring, then its public classes and functions in source order."""
    path, _ = _source(module)
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out = [f"## `{module}`\n", _text(ast.get_docstring(tree))]
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
            out.append(_class(node, 3))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("_"):
            out.append(_function(node, 3))
    return "\n".join(part for part in out if part)


def _file_block(relative: str) -> str:
    """A repository file, folded: the site's snippet plugin puts its text in the code block."""
    language = {".toml": "toml", ".json": "json", ".py": "python"}.get(Path(relative).suffix, "text")
    return f"<details>\n<summary><code>{relative}</code></summary>\n\n```{language}\n--8<-- \"{relative}\"\n```\n\n</details>\n"



API = {
    "Configuration": ["harness.config", "harness.config.agent", "harness_eval.experiments"],
    "Episode runtime": ["harness.runtime.decision.messages", "harness.runtime.execution.kernel",
                        "harness.runtime.execution.session", "harness.runtime.safety.input", "harness.runtime.safety.shield",
                        "harness.runtime.execution.control"],
    "Events and the reactive layer": ["harness.runtime.events", "harness.runtime.reactive.rules"],
    "Tick and entries": ["harness.runtime.tick", "harness.runtime.execution.entries"],
    "Conversations": ["harness.runtime.decision.model", "harness.runtime.task.run", "harness.core.spans"],
    "Skills and prompts": ["harness.runtime.execution.skills", "harness.runtime.decision.prompts"],
    "Suites and reports": ["harness_eval.suite"],
    "Services": ["harness.services.registry", "harness.services.placement", "harness_local_models.deploy",
                 "harness_local_models.supervisor", "harness.services.broker"],
    "Session host": ["harness.host.http", "harness.host.client", "harness.core.episodes", "harness.transcript",
                     "harness.terminal",
                     "harness.extensions"],
    "Robots and workers": ["harness.core.remote", "harness.core.worker", "harness.embodiments"],
}


def api_pages() -> dict:
    pages = {}
    index = ["# Python API\n", "Generated from the docstrings. Most users need only the CLI and the "
             "configuration files; these are the modules to build on.\n"]
    for group, modules in API.items():
        slug = re.sub(r"[^a-z]+", "-", group.lower()).strip("-")
        body = [f"# {group}\n"]
        for module in modules:
            body.append(_api_module(module))
        pages[f"reference/api/{slug}.md"] = "\n".join(body)
        index.append(f"- [{group}](/docs/reference/api/{slug}/): " + ", ".join(f"`{module}`" for module in modules))
    pages["reference/api/index.md"] = "\n".join(index) + "\n"
    return pages


# -- all pages ---------------------------------------------------------------------------------

def environment_page() -> str:
    """environment/README.md, the one source of how environments are installed and pinned."""
    text = (BUILTIN / "environment" / "README.md").read_text(encoding="utf-8")
    return "# Environments\n\n" + text.split("\n", 1)[1].lstrip("\n")


def pages() -> dict:
    out = {"reference/cli.md": cli_page(), "reference/configuration.md": configuration_page(),
           "reference/environment.md": environment_page(),
           "reference/agent.md": agent_page(), "reference/configs.md": configs_page()}
    out.update(skill_pages())
    out.update(api_pages())
    return out


README_TABLES = {"skills": lambda: skills_table(), "packages": lambda: packages_table()}


def packages_table() -> str:
    """The packages of this repository (packages/<name>/package.toml): what each is and provides."""
    from harness.packages.manifest import load

    rows = []
    for path in sorted((ROOT / "packages").glob("*/package.toml")):
        package = load(path.parent)
        provides = "; ".join(f"{kind} {', '.join(names)}" for kind, names in package.provides.items()
                             if kind in ("embodiments", "benches", "skills", "services", "commands"))
        rows.append((f"[{package.name}](https://harness.lmms-lab.com/packages/{package.name}/)", package.summary,
                     ", ".join(package.depends) or "–", provides or "–"))
    return _table(["Package", "What it is", "Depends on", "Provides"], rows)


def readme_with_tables(text: str) -> str:
    """README.md with each `<!-- generated: NAME -->` ... `<!-- /generated: NAME -->` block
    rendered afresh."""
    for name, render in README_TABLES.items():
        pattern = re.compile(rf"(<!-- generated: {name} -->\n).*?(<!-- /generated: {name} -->)", re.S)
        text = pattern.sub(lambda match: match.group(1) + render() + match.group(2), text)
    return text


def site_page(path: str, text: str) -> str:
    """A generated page as the site reads it: its `# Title` becomes the frontmatter title, and
    a directory's index comes first in that directory's part of the sidebar."""
    title, _, body = text.partition("\n")
    front = ["---", f"title: {json.dumps(title.removeprefix('# ').strip())}"]
    if path.endswith("/index.md"):
        front += ["sidebar:", "  label: Overview", "  order: 0"]
    return "\n".join(front + ["---", ""]) + "\n" + body.lstrip("\n")


def write_pages(content=CONTENT) -> list:
    """Writes every generated page under `content`, replacing the generated directories whole
    so a removed skill or service leaves no page behind."""
    generated = pages()
    for directory in {Path(path).parent for path in generated} - {Path("reference")}:
        shutil.rmtree(content / directory, ignore_errors=True)
    for path, text in generated.items():
        target = content / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(site_page(path, text), encoding="utf-8", newline="\n")
    return sorted(generated)


if __name__ == "__main__":
    command = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    command.add_argument("--readme", action="store_true", help="rewrite the generated tables in README.md")
    command.add_argument("--write", action="store_true", help="write the pages into docs/src/content/docs")
    command.add_argument("--list", action="store_true", help="print the pages this generates")
    options = command.parse_args()
    if options.write:
        print(f"{len(write_pages())} reference pages written to {CONTENT.relative_to(ROOT).as_posix()}")
    if options.readme:
        readme = ROOT / "README.md"
        readme.write_text(readme_with_tables(readme.read_text(encoding="utf-8")), encoding="utf-8", newline="\n")
    if options.list or not (options.readme or options.write):
        print("\n".join(sorted(pages())))
