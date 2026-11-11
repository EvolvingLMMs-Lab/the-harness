"""A versioned library of what the harness has learned, for any action scenario (a robot,
a desktop, a website, a game): one learner fills it (runtime/learning/learner.py), in a run (in-context:
an entry admitted takes effect at once) and between runs (self-improvement on development
seeds), and evaluation reads it frozen.

Layout of a library directory:

    notes/*.md          high-level notes, appended to the system prompt
    memory/*.md         long-term memory entries, not in the prompt; programs find
                        them with recall() beside the run's own (runtime/task/context.py;
                        layer: notes)
    skills/*.py         low-level skills and handlers, executed in the kernel
                        namespace before the first program (layer: low)
    reactive/*.py       guard/controller helpers, executed only when the reactive
                        layer is enabled (layer: reactive)
    tests/<name>.py     the test of skills/<name>.py or reactive/<name>.py: Python that
                        uses the entry and raises when it does not work
    skills/<name>.files/    an entry's attachments (a trained model's weights...)
    library.toml        optional: `notes_title`, the line the notes stand under in the
                        prompt (a library written by hand holds knowledge, not lessons)
    index.json          per entry: its evidence, whether it was learned actively or
                        passively, by whom, when, its test runs and its uses (each
                        execution of its code in a run that learns: memory.fold_uses;
                        learner.py); not part of the version
    admissions.jsonl    one line an admission: section, file, the sha256 of its bytes,
                        the version after it (what an audit checks the entries against)
    candidates/         entries proposed and waiting for validation on development seeds
                        (not loaded, not part of the version)

Each entry is one file (with its test and attachments). The library version is the sha256
over the loaded entries' relative paths and bytes, their tests and attachments included;
every episode records it, and every admission changes it. An entry's evidence grades it
(EVIDENCE): a library loads the entries at or above its `load` level, and one that failed
never. Evaluation uses a single version, and a library may be restricted to some layers
(Tab. 8 ablation).
"""

import ast
import base64
import hashlib
from functools import wraps
from graphlib import TopologicalSorter
import inspect
import json
import time
from types import FunctionType
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from pathlib import Path
import tomllib
from weakref import WeakKeyDictionary

from harness.core import atomic_write


SECTIONS = {"notes": ".md", "memory": ".md", "skills": ".py", "reactive": ".py"}
# Library layers (Tab. 8 ablation) and the sections each one enables.
LAYER_OF = {"notes": "notes", "memory": "notes", "skills": "skills", "reactive": "reactive"}
LAYERS = ("notes", "skills", "reactive")
# What the notes stand under in the prompt, unless library.toml names another title.
NOTES_TITLE = "Notes from earlier episodes:"
# How well an entry is known to work, weakest first: proposed (no check yet), provisional
# (its own test passed in a run; a note or memory entry the model admitted), replayed (its
# test passed again at the start of a later run), validated (it raised the score on
# held-out development seeds). An entry the library holds without an index row was put
# there by hand or by self-improvement before the index: validated. A failed one never loads.
EVIDENCE = ("proposed", "provisional", "replayed", "validated")
FAILED = "failed"
INDEX = "index.json"
ADMISSIONS = "admissions.jsonl"
TESTS = "tests"
CANDIDATES = "candidates"
_code_origins = WeakKeyDictionary()
_code_active = WeakKeyDictionary()



@dataclass(frozen=True)
class Revision:
    key: str
    source: bytes
    test: bytes | None = None
    attachments: tuple = ()
    dependencies: tuple = ()
    bindings: tuple = ()

    @property
    def source_sha256(self):
        return hashlib.sha256(self.source).hexdigest()

    @property
    def revision(self):
        return hashlib.sha256(self.pack()).hexdigest()

    def pack(self):
        encode = lambda data: base64.b64encode(data).decode("ascii")
        return json.dumps({"key": self.key, "source": encode(self.source),
                           "test": None if self.test is None else encode(self.test),
                           "attachments": [[name, encode(data)] for name, data in self.attachments],
                           "dependencies": list(self.dependencies),
                           **({"bindings": list(self.bindings)} if self.bindings else {})},
                          sort_keys=True, separators=(",", ":")).encode("utf-8")

    @classmethod
    def unpack(cls, data):
        row = json.loads(data)
        return cls(row["key"], base64.b64decode(row["source"]),
                   None if row["test"] is None else base64.b64decode(row["test"]),
                   tuple((name, base64.b64decode(value)) for name, value in row["attachments"]),
                   tuple(tuple(dependency) for dependency in row["dependencies"]),
                   tuple(tuple(binding) for binding in row.get("bindings", ())))

    def save(self, directory):
        path = Path(directory) / ".revisions" / self.revision
        if not path.is_file():
            atomic_write(path, self.pack())
        return self.revision

    @classmethod
    def read(cls, directory, revision):
        if len(revision) != 64 or any(char not in "0123456789abcdef" for char in revision):
            raise ValueError("invalid library revision")
        data = (Path(directory) / ".revisions" / revision).read_bytes()
        if hashlib.sha256(data).hexdigest() != revision:
            raise ValueError(f"library revision {revision} has changed")
        return cls.unpack(data)


@dataclass(frozen=True)
class LibrarySnapshot:
    directory: Path
    layers: tuple
    load: str
    version: str
    entries: tuple
    index_json: bytes
    settings: bytes

    @property
    def index(self):
        return json.loads(self.index_json)

    def manifest(self):
        return {"directory": str(self.directory), "layers": list(self.layers), "version": self.version,
                **({"load": self.load} if self.load != "proposed" else {}),
                "entries": {section: [item.key.split("/", 1)[1] for item in self.entries
                                      if item.key.startswith(section + "/")] for section in SECTIONS}}

    def notes(self):
        texts = [item.source.decode("utf-8").strip() for item in self.entries if item.key.startswith("notes/")]
        title = str(tomllib.loads(self.settings.decode("utf-8")).get("notes_title") or NOTES_TITLE)
        return f"\n{title}\n" + "\n".join(f"- {text}" for text in texts) + "\n" if texts else ""

    def api_summary(self, active):
        return active_summary(item for item in self.entries if item.key in active)


def active_summary(items):
    lines = [line for item in items for line in summary_lines(item.source.decode("utf-8"))]
    return "\nLibrary skills (already defined in your kernel):\n" + "\n".join(lines) + "\n" if lines else ""


def executable(key):
    return key.startswith(("skills/", "reactive/"))


def eligible(item, row, layers, load):
    section = item.key.split("/", 1)[0]
    evidence = row.get("evidence", "validated")
    if not selects(section, evidence, layers, load):
        return False
    if not executable(item.key) or not row or row.get("origin") == "hand":
        return True
    proof = row.get("proof") or {}
    return (evidence in ("provisional", "replayed", "validated")
            and proof.get("revision") == item.revision and bool(proof.get("conditions")))



def _verified_bindings(api, bindings):
    """Pin fixture actions to the original kernel API and the tested implementation."""
    from types import CodeType, MethodType

    scope = {}
    compiled = {}
    for name, module, owner, digest in bindings:
        action = api.get(name)
        if not isinstance(action, MethodType) or action.__module__ != module:
            raise ValueError(f"verified binding {name} is unavailable")
        code = action.__func__.__code__
        if code.co_filename not in compiled:
            data = Path(code.co_filename).read_bytes()
            compiled[code.co_filename] = (hashlib.sha256(data).hexdigest(),
                                          compile(data, code.co_filename, "exec", dont_inherit=True))
        source_digest, source = compiled[code.co_filename]
        if source_digest != digest or not any(
            code == method for cls in source.co_consts if isinstance(cls, CodeType) and cls.co_name == owner
            for method in cls.co_consts if isinstance(method, CodeType) and method.co_name == name
        ):
            raise ValueError(f"verified binding {name} has a different implementation")
        scope[name] = action
    return scope


def stage_entries(items, namespace, active, reactive, *, api=None):
    from harness.runtime.execution.entries import ClosedLoop
    from harness.runtime.reactive.rules import _stage_rules
    from harness.core import spans

    batch = {item.key: (item, hand) for item, hand in items}
    targets = {key: item.revision for key, (item, _) in batch.items()}
    order = TopologicalSorter({key: [dep for dep, _ in item.dependencies if dep in batch]
                               for key, (item, _) in batch.items()}).static_order()
    revisions = {**{key: row[0] for key, row in active.items()}, **targets}
    for key, (_, _, dependencies) in active.items():
        if key not in targets and any(revisions.get(dep) != required for dep, required in dependencies):
            raise ValueError(f"replace {key} together with its changed dependency")
    scope = dict(namespace)
    owners = dict(active)
    for key in targets:
        for name, value in owners.get(key, (None, {}))[1].items():
            if scope.get(name) is value:
                del scope[name]

    with _stage_rules(reactive, targets) as staged_rules:
        for key in order:
            item, hand = batch[key]
            for key, required in item.dependencies:
                if revisions.get(key) != required:
                    raise ValueError(f"{item.key} needs {key} at {required}")
            execution = _verified_bindings(api or {}, item.bindings) if item.bindings else scope
            if item.bindings:
                execution["__builtins__"] = {}
            before = dict(execution)
            origin = item.key, item.source_sha256, item.revision
            tree = ast.parse(item.source, f"<library {item.key}>")
            if not hand:
                for node in tree.body:
                    if not isinstance(node, (ast.Import, ast.ImportFrom, ast.FunctionDef, ast.ClassDef,
                                             ast.AsyncFunctionDef, ast.Assign, ast.AnnAssign, ast.Expr)):
                        raise ValueError(f"{item.key} has unsupported initialization")
                    for child in _initialization(node):
                        if isinstance(child, ast.Call):
                            if (not isinstance(child.func, ast.Name)
                                    or child.func.id not in ("when", "watch", "on", "rule")):
                                raise ValueError(f"{item.key} must put runtime actions inside a callable")
                        if isinstance(child, (ast.Attribute, ast.Subscript)) and isinstance(child.ctx, ast.Store):
                            raise ValueError(f"{item.key} cannot modify live objects during activation")
            if staged_rules is not None:
                staged_rules.library_origin = origin
            exec(compile(tree, f"<library {item.key}>", "exec"), execution)
            exports = {name: value for name, value in execution.items() if not name.startswith("__")
                       and (name not in before or before[name] is not value)}
            if item.bindings and exports.keys() & (api or {}).keys():
                raise ValueError(f"{item.key} would replace a built-in skill")
            for name, value in exports.items():
                if isinstance(value, type) and issubclass(value, ClosedLoop):
                    _code_origins[value] = origin
                    _code_active[value] = active
                elif isinstance(value, FunctionType) and value.__globals__ is execution:
                    wrapped = _tracked(value, origin, active, spans)
                    scope[name] = exports[name] = wrapped
            scope.update(exports)
            owners[item.key] = (item.revision, exports, item.dependencies)
    return scope, owners, staged_rules


def _initialization(node):
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        fields = (*node.decorator_list, *node.args.defaults, *filter(None, node.args.kw_defaults))
        return (child for part in fields for child in ast.walk(part))
    if isinstance(node, ast.ClassDef):
        fields = (*node.bases, *node.decorator_list, *node.keywords)
        return (*[child for part in fields for child in ast.walk(part)],
                *[child for part in node.body for child in _initialization(part)])
    return ast.walk(node)


def _tracked(function, origin, active, spans):
    @contextmanager
    def execution():
        if active.get(origin[0], (None,))[0] != origin[2]:
            raise RuntimeError(f"library revision for {origin[0]} is no longer active")
        start = time.monotonic()
        try:
            yield
        except BaseException as error:
            spans.step(function.__name__, 1, "gave up", False, time.monotonic() - start,
                       type(error).__name__, library=origin)
            raise
        else:
            spans.step(function.__name__, 1, "done", True, time.monotonic() - start, library=origin)

    if inspect.iscoroutinefunction(function):
        @wraps(function)
        async def call(*args, **kwargs):
            with execution():
                return await function(*args, **kwargs)
    elif inspect.isasyncgenfunction(function):
        @wraps(function)
        async def call(*args, **kwargs):
            with execution():
                async for result in function(*args, **kwargs):
                    yield result
    elif inspect.isgeneratorfunction(function):
        @wraps(function)
        def call(*args, **kwargs):
            with execution():
                return (yield from function(*args, **kwargs))
    else:
        @wraps(function)
        def call(*args, **kwargs):
            with execution():
                return function(*args, **kwargs)
    _code_origins[call] = origin
    return call


def publish_entries(staged, namespace, active, reactive):
    scope, owners, rules = staged
    with reactive.library_boundary if rules is not None else nullcontext():
        for key, (_, exports, _) in active.items():
            if key in owners and owners[key][1] is not exports:
                for name, value in exports.items():
                    if namespace.get(name) is value and name not in scope:
                        del namespace[name]
        namespace.update(scope)
        active.update(owners)
        if rules is not None:
            reactive._publish_rules(rules)


def assert_active(code):
    origin = _code_origins.get(code)
    active = _code_active.get(code)
    if origin is not None and active is not None and active.get(origin[0], (None,))[0] != origin[2]:
        raise RuntimeError(f"library revision for {origin[0]} is no longer active")


def code_origin(cls):
    return _code_origins.get(cls)


def rank(evidence) -> int:
    """An evidence level's place in EVIDENCE (-1 for failed or unknown)."""
    return EVIDENCE.index(evidence) if evidence in EVIDENCE else -1


def selects(section, evidence, layers, load) -> bool:
    """Whether this revision passes a reader's library selection."""
    return LAYER_OF.get(section) in layers and rank(evidence) >= rank(load) >= 0


class Library:
    def __init__(self, directory, layers=("notes", "skills", "reactive"), load="proposed"):
        self.directory = Path(directory).resolve()
        unknown = set(layers) - set(LAYERS)
        if unknown:
            raise ValueError(f"Unknown library layers: {sorted(unknown)}")
        if load not in EVIDENCE:
            raise ValueError(f"library load is one of {list(EVIDENCE)}, not {load!r}")
        self.layers = tuple(layers)
        self.load = load
        if not self.directory.is_dir():
            raise ValueError(f"Library directory not found: {self.directory}")

    def index(self) -> dict:
        """{"<section>/<file>": {"evidence", "source", "origin", ...}} (learner.py)."""
        path = self.directory / INDEX
        try:
            data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        except (OSError, ValueError):
            data = {}
        return data if isinstance(data, dict) else {}

    def evidence(self, section, filename, index=None) -> str:
        row = (self.index() if index is None else index).get(f"{section}/{filename}")
        return row.get("evidence", "validated") if isinstance(row, dict) else "validated"

    def entries(self, section):
        if LAYER_OF[section] not in self.layers:
            return []
        folder = self.directory / section
        if not folder.is_dir():
            return []
        index = self.index()
        return sorted(path for path in folder.glob(f"*{SECTIONS[section]}")
                      if not (index.get(f"{section}/{path.name}") or {}).get("forgotten")
                      and selects(section, self.evidence(section, path.name, index), self.layers, self.load))

    def test(self, section, filename) -> Path | None:
        """The test of a code entry, if it has one."""
        path = self.directory / TESTS / f"{Path(filename).stem}.py"
        return path if section in ("skills", "reactive") and path.is_file() else None

    def attachments(self, section, filename) -> list[Path]:
        folder = self.directory / section / f"{Path(filename).stem}.files"
        return sorted(path for path in folder.rglob("*") if path.is_file()) if folder.is_dir() else []

    def capture(self, *, include_unselected=False):
        """Read one index and each selected payload once."""
        from harness.runtime.learning.experience import MIGRATION, legacy_entries

        index = self.index()
        legacy = {}
        if "notes" in self.layers and not index.get(MIGRATION):
            for item in list(legacy_entries(self.directory, index)):
                key = item["id"]
                if key not in index:
                    legacy[key] = Revision(key, item["text"].encode("utf-8"))
                    index[key] = {"memory": item, "evidence": "validated", "origin": "legacy"}
        settings = self.directory / "library.toml"
        raw_settings = settings.read_bytes() if settings.is_file() else b""
        digest = hashlib.sha256()
        if raw_settings:
            digest.update(b"library.toml\0" + raw_settings + b"\0")
        found = []
        for section, suffix in SECTIONS.items():
            folder = self.directory / section
            paths = {path.name: path for path in folder.glob(f"*{suffix}")}
            paths.update({key.split("/", 1)[1]: folder / key.split("/", 1)[1]
                          for key, row in index.items() if key.startswith(section + "/") and (row.get("revision") or key in legacy)})
            for name, path in sorted(paths.items()):
                key = f"{section}/{name}"
                row = index.get(key) or {}
                selected = selects(section, row.get("evidence", "validated"), self.layers, self.load)
                if row.get("forgotten") or not selected and not include_unselected:
                    continue
                if key in legacy:
                    item = legacy[key]
                elif row.get("revision"):
                    item = Revision.read(self.directory, row["revision"])
                    if item.key != key:
                        raise ValueError(f"library index points {key} at a different entry")
                else:
                    test = self.test(section, name)
                    attachments = self.attachments(section, name)
                    item = Revision(key, path.read_bytes(), test.read_bytes() if test else None,
                                    tuple((part.relative_to(self.directory).as_posix(), part.read_bytes())
                                          for part in attachments))
                found.append(item)
                if not selected:
                    continue
                parts = [(item.key, item.source)]
                if item.test is not None:
                    parts.append((f"{TESTS}/{path.stem}.py", item.test))
                parts.extend(item.attachments)
                for relative, data in parts:
                    digest.update(relative.encode() + b"\0" + data + b"\0")
                if row.get("memory"):
                    digest.update(json.dumps(row["memory"], sort_keys=True).encode("utf-8"))
                if item.dependencies:
                    digest.update(json.dumps(item.dependencies).encode("utf-8"))
                if item.bindings:
                    digest.update(json.dumps(item.bindings).encode("utf-8"))
        return LibrarySnapshot(self.directory, self.layers, self.load, digest.hexdigest(), tuple(found),
                               json.dumps(index).encode("utf-8"), raw_settings)

    def version(self) -> str:
        return self.capture().version

    def manifest(self) -> dict:
        return self.capture().manifest()

    def notes(self) -> str:
        return self.capture().notes()

    def api_summary(self, reactive_enabled: bool) -> str:
        captured = self.capture()
        active = {item.key for item in captured.entries if item.key.startswith("skills/")
                  or reactive_enabled and item.key.startswith("reactive/")}
        return captured.api_summary(active)


def summary_lines(code: str) -> list[str]:
    """`  name(args)  first docstring line` of each public function and class of `code`
    (a class: its parameters are the loop's; a closed loop is called like a function)."""

    lines = []
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return lines
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and not node.name.startswith("_"):
            args = ", ".join(a.arg for a in node.args.args) if isinstance(node, ast.FunctionDef) else "..."
            doc = (ast.get_docstring(node) or "").strip().splitlines()
            lines.append(f"  {node.name}({args})" + (f"  {doc[0]}" if doc else ""))
    return lines


def library_for(runtime: dict, base: Path) -> Library:
    """The library a [runtime.library] table names (its path relative to `base`, or under
    $HARNESS_HOME); one that learns is created empty when it is not there yet."""
    from harness.runtime.learning.learner import library_path, settings

    config = runtime["library"]
    path = library_path(config["path"])
    directory = (base / path).resolve() if not path.is_absolute() else path
    chosen = settings(config)
    if chosen["learn"] == "on":
        for section in SECTIONS:
            (directory / section).mkdir(parents=True, exist_ok=True)
    return Library(directory, config.get("layers", ("notes", "skills", "reactive")), chosen["load"])
