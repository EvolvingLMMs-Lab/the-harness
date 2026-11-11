"""harness.sdk: the one module a package imports.

A package's skills, benches, workers and services import the harness only from here
(tools/check.py refuses any other `harness` import), so the harness can change inside
without breaking them; a change here that breaks a package raises the harness's major
version. Its names, by what they are for:

    Skills         ClosedLoop, Result, Stop, wait_until,
                   span, spans, control, events, Escalation, Event, ExecutionTrace,
                   ProgramFinished, record_kind, ReactiveFault, call_reactive,
                   json_list (the JSON list in a model's reply),
                   Learner, candidate, entry_key, Library, SECTIONS, WorkingMemory, MemoryKind, memory_entries,
                   keep_probe, BUILTIN_ACTIONS, OPEN_GRIPPER, STOP, HOLD, BACK_OFF, Refused
    Sessions       EpisodeCore, create_session, session_class (an embodiment kind's kernel
                   session builds on the episode core), PhysicalInput, REMEMBER
    Workers        WORKER_METHODS, create_server, BenchWorker (what a benchmark's worker
                   shares), Action, Observation, Transition, EpisodeCursor, OutcomeToken,
                   pid_alive, file_lock, start_detached, data_url, image_data_url, decode_data_url, encode_png, fit_into,
                   finite_bounds, validate_vector, validate_position,
                   ShieldResult, PASS, REJECTED, finite, in_screen, bounded, reject,
                   Lanes, free_port, free_ports, OwnPort, git_revision, now, stamp
    Services       service_environment
    Benches        BenchSpec, bench_spec (a bench's bench.toml); Bench, load_bench
                   (its hooks: the eval package's, imported only there); load_deploy,
                   load_embodiment, TaskConfig, scripted_models, apply_sets, load_layered,
                   DEFAULT_AGENT, resolve_agent, repo_modules, bench_environment, environments,
                   read_toml, parse_set, service_names, embodiment_profile
    Services       ensure, McpClient, McpError, McpSession, McpSessionGone, MCP_PROTOCOL_VERSION (an MCP
                   session over another transport), load_services, SERVICES_ROOT, ServiceSpec
    Paths          ROOT, CHECKOUT_ROOT, home, active_packages, import_roots, python_path, third_party, find,
                   atomic_write (a whole file or none)
    Session host   Host, HttpServer, sessions (LIVE, ENDED, live, word, ended_status), serve_files;
                   TaskHost, TaskServer (the server a package's API handlers are given, and its tests')
    Settings       data, Settings, SETTINGS_FILE (the user's configuration file),
                   Credentials (the API keys: the environment or [keys]),
                   toml_dumps (the one TOML writer)
    Version        version (the harness's)
    Agents         Trace (an agent's trace: what another harness's agent run as a sub-agent
                   writes, runtime/task/delegation.py), read_records (an episode's trace as written)
    HTTP           open_url, post_json (a request to a worker, a service or a site)
    Files          digest, fetch_verified (a download kept only with the expected hash)
    Media          ffmpeg, probe, FRAMES (probe()'s start_from for a start read from the frames)
    Runs           run_name, episodes (summary, usage, ending), resolve_run
    Text           format (cost, duration, clock, timestamp), transcript, approval (the sensitive kinds,
                   request(), and the words of an approval: WORDS, say)
    Evaluation     ResolvedAgent, overridden_agent, task_config, bench_names, declares_channels,
                   TaskRun, serve_worker, UsageError (a command's usage error: exit status 2),
                   cli_output and cli_table (a command's JSON and text table, as the core's print them)
                   and the terminal chat's timeline (tui_timeline)

Everything here is imported when it is first used, so importing the sdk costs nothing
and needs nothing beyond the standard library.
"""

import importlib


# name -> "module:attribute" (or "module" for a module).
_NAMES = {
    "Evidence": "harness.core.artifacts:Evidence",
    "WorkspaceProvider": "harness.host.workspaces:WorkspaceProvider",
    "WorkerPool": "harness.host.workers:WorkerPool",
    "Worker": "harness.host.workers:Worker",
    "WorkerCancelled": "harness.host.workers:Cancelled",
    # Skills: bounded executions, events, spans, learning, reactions.
    "ClosedLoop": "harness.runtime.execution.entries:ClosedLoop",
    "Result": "harness.runtime.execution.entries:Result",
    "Stop": "harness.runtime.execution.entries:Stop",
    "wait_until": "harness.core.wait:wait_until",
    "span": "harness.core.spans:span",
    "spans": "harness.core.spans",
    "control": "harness.runtime.execution.control",
    "events": "harness.runtime.events",
    "Escalation": "harness.runtime.events:Escalation",
    "Event": "harness.runtime.events:Event",
    "ExecutionTrace": "harness.runtime.events:ExecutionTrace",
    "EpisodeEnded": "harness.runtime.events:EpisodeEnded",
    "Tick": "harness.runtime.tick:Tick",
    "WorkerPipe": "harness.core.worker_pipe:WorkerPipe",
    "WorkerRejected": "harness.core.worker_pipe:WorkerRejected",
    "linux_sandbox": "harness.core.linux_sandbox",
    "ProgramFinished": "harness.runtime.events:ProgramFinished",
    "record_kind": "harness.runtime.events:record_kind",
    "ReactiveFault": "harness.runtime.reactive.rules:ReactiveFault",
    "call_reactive": "harness.runtime.reactive.rules:call_reactive",
    "Learner": "harness.runtime.learning.learner:Learner",
    "candidate": "harness.runtime.learning.learner:candidate",
    "entry_key": "harness.runtime.learning.learner:entry_key",
    "Library": "harness.runtime.learning.library:Library",
    "WorkingMemory": "harness.runtime.task.context:WorkingMemory",
    "memory_entries": "harness.runtime.learning.views:library_entries",
    "MemoryKind": "harness.runtime.task.context:Kind",
    "SECTIONS": "harness.runtime.learning.library:SECTIONS",
    "BUILTIN_ACTIONS": "harness.runtime.reactive.rules:BUILTIN_ACTIONS",
    "OPEN_GRIPPER": "harness.runtime.reactive.rules:OPEN_GRIPPER",
    "STOP": "harness.runtime.reactive.rules:STOP",
    "HOLD": "harness.runtime.reactive.rules:HOLD",
    "BACK_OFF": "harness.runtime.reactive.rules:BACK_OFF",
    "Refused": "harness.runtime.tick:Refused",
    "keep_probe": "harness.runtime.learning.active:keep",
    # Sessions: what an embodiment kind's kernel session builds on.
    "EpisodeCore": "harness.runtime.execution.session:EpisodeCore",
    "create_session": "harness.runtime.execution.session:create_session",
    "session_class": "harness.runtime.execution.session:session_class",
    "PhysicalInput": "harness.runtime.safety.input:PhysicalInput",
    "input_sent": "harness.runtime.safety.input:input_sent",
    "REMEMBER": "harness.runtime.safety.input:REMEMBER",
    # Workers: the protocol, what crosses it, the shields.
    "WORKER_METHODS": "harness.core.worker:WORKER_METHODS",
    "create_server": "harness.core.worker:create_server",
    "Action": "harness.core.contracts:Action",
    "Observation": "harness.core.contracts:Observation",
    "RemoteEnvironment": "harness.core.remote:RemoteEnvironment",
    "Place": "harness.runtime.task.delegation:Place",
    "Transition": "harness.core.contracts:Transition",
    "EpisodeCursor": "harness.core.codec:EpisodeCursor",
    "OutcomeToken": "harness.core.codec:OutcomeToken",
    "pid_alive": "harness.core.procs:pid_alive",
    "file_lock": "harness.core.procs:file_lock",
    "SHARED_LOCK_DIR": "harness.core.procs:SHARED_LOCK_DIR",
    "start_detached": "harness.core.procs:start_detached",
    "service_environment": "harness.core.procs:service_environment",
    "data_url": "harness.core.codec:data_url",
    "image_data_url": "harness.core.codec:image_data_url",
    "decode_data_url": "harness.core.codec:decode_data_url",
    "encode_png": "harness.core.codec:encode_png",
    "fit_into": "harness.core.codec:fit_into",
    "finite_bounds": "harness.core.codec:finite_bounds",
    "validate_vector": "harness.core.codec:validate_vector",
    "ShieldResult": "harness.runtime.safety.shield:ShieldResult",
    "finite": "harness.runtime.safety.shield:finite",
    "in_screen": "harness.runtime.safety.shield:in_screen",
    "bounded": "harness.runtime.safety.shield:bounded",
    "reject": "harness.runtime.safety.shield:reject",
    "PASS": "harness.runtime.safety.shield:PASS",
    "REJECTED": "harness.runtime.safety.shield:REJECTED",
    "Lanes": "harness.core.lanes:Lanes",
    # Benches: the hooks, embodiments, configurations, environments.
    # A bench's hooks are the eval package's: a bench's bench.py subclasses Bench, and only
    # the eval package imports it (benches run over tasks and seeds there).
    "BenchWorker": "harness.core.worker:BenchWorker",
    "free_port": "harness.core.ports:free_port",
    "OwnPort": "harness.core.ports:OwnPort",
    "git_revision": "harness.core.trace:git_revision",
    "now": "harness.core.trace:now",
    "stamp": "harness.core.trace:stamp",
    "free_ports": "harness.core.ports:free_ports",
    "Bench": "harness_eval.bench:Bench",
    "load_bench": "harness_eval.bench:load_bench",
    "BenchSpec": "harness.bench:BenchSpec",
    "bench_spec": "harness.bench:bench_spec",
    "load_deploy": "harness.services.placement:load_deploy",
    "load_embodiment": "harness.embodiments:load_embodiment",
    "TaskConfig": "harness.config.agent:TaskConfig",
    "scripted_models": "harness.runtime.decision.model:scripted_models",
    "apply_sets": "harness.config:apply_sets",
    "load_layered": "harness.config:load_layered",
    "DEFAULT_AGENT": "harness.config.agent:DEFAULT_AGENT",
    "resolve_agent": "harness.config.agent:resolve_agent",
    "repo_modules": "harness.runtime.execution.kernel:repo_modules",
    "read_toml": "harness.config:read_toml",
    "toml_dumps": "harness.config:dumps",
    "parse_set": "harness.config:parse_set",
    "service_names": "harness.config.agent:_service_names",
    "embodiment_profile": "harness.embodiments:profile",
    "bench_environment": "harness.packages.provision:bench_environment",
    "environments": "harness.packages.environments",
    # Services.
    "ensure": "harness.services.broker:ensure",
    "StdioServer": "harness.services.mcp_stdio:StdioServer",
    "McpClient": "harness.services.mcp:McpClient",
    "McpError": "harness.services.mcp:McpError",
    "McpSession": "harness.services.mcp:McpSession",
    "McpSessionGone": "harness.services.mcp:SessionGone",
    "MCP_PROTOCOL_VERSION": "harness.services.mcp:PROTOCOL_VERSION",
    "load_services": "harness.services.registry:load_services",
    "SERVICES_ROOT": "harness.services.registry:SERVICES_ROOT",
    "ServiceSpec": "harness.services.registry:ServiceSpec",
    "bench_environment_status": "harness.packages.provision:bench_environment_status",
    "install_bench_environment": "harness.packages.provision:install_bench_environment",
    "providers": "harness.providers",
    "model_list": "harness.model_list",
    "RemoteConversation": "harness.host.client:RemoteConversation",
    # Paths.
    "ROOT": "harness.paths:ROOT",
    "CHECKOUT_ROOT": "harness.paths:CHECKOUT_ROOT",
    "home": "harness.paths:home",
    "import_roots": "harness.paths:import_roots",
    "active_packages": "harness.paths:packages",
    "python_path": "harness.paths:python_path",
    "third_party": "harness.paths:third_party",
    "find": "harness.paths:find",
    # Settings: the user's configuration.
    "data": "harness.paths:data",
    "Settings": "harness.settings:Settings",
    "Credentials": "harness.settings:Credentials",
    "SETTINGS_FILE": "harness.settings:FILE",
    "ffmpeg": "harness.core.media:ffmpeg",
    "digest": "harness.packages.fetch:digest",
    "fetch_verified": "harness.packages.fetch:fetch_verified",
    "open_url": "harness.core.http:open_url",
    "post_json": "harness.core.http:post_json",
    "probe": "harness.core.media:probe",
    "FRAMES": "harness.core.media:FRAMES",
    # The session host: its client and its HTTP server.
    "Host": "harness.host:Host",
    "HttpServer": "harness.host.http:Server",
    "TaskHost": "harness.host.tasks:TaskHost",
    "TaskServer": "harness.host.tasks:TaskServer",
    "sessions": "harness.host.sessions",
    # Evaluation (the eval package): experiments, suites, their command line and pages.
    "ResolvedAgent": "harness.config.agent:ResolvedAgent",
    "overridden_agent": "harness.config.agent:overridden_agent",
    "task_config": "harness.config.agent:task_config",
    "sha256": "harness.core:sha256",
    "bench_names": "harness.bench:bench_names",
    "declares_channels": "harness.bench:declares_channels",
    "locate": "harness.paths:locate",
    "roots": "harness.paths:roots",
    "packages": "harness.paths:packages",
    "PACKAGE": "harness.paths:PACKAGE",
    "KERNEL_PYTHON_ENV": "harness.runtime.execution.kernel:KERNEL_PYTHON_ENV",
    "resolve_skills": "harness.config.agent:resolve_for",
    "LAYER_DEFAULTS": "harness.runtime.execution.skills:LAYER_DEFAULTS",
    "active": "harness.runtime.learning.active",
    "learning_settings": "harness.runtime.learning.learner:settings",
    "TaskRun": "harness.runtime.task.run:TaskRun",
    "think": "harness.runtime.decision.thoughts:think",
    "ChatModel": "harness.runtime.decision.model:ChatModel",
    "USAGE": "harness.runtime.decision.model:USAGE",
    "add_usage": "harness.runtime.decision.model:add_usage",
    "json_list": "harness.runtime.decision.protocol:json_list",
    "load_skills": "harness.runtime.execution.skills:load_skills",
    "write_json": "harness.core.trace:write_json",
    "atomic_write": "harness.core:atomic_write",
    "serve_worker": "harness.core.worker:main",
    "first": "harness.extensions:first",
    "episodes": "harness.core.episodes",
    "resolve_run": "harness.host:resolve_run",
    "UsageError": "harness.cli:UsageError",
    "cli_output": "harness.cli:output",
    "cli_table": "harness.cli:table",
    # The terminal chat's timeline (the app package's harness timeline).
    "tui_timeline": "harness.tui:timeline",
    "serve_files": "harness.host.http:serve_files",
    "version": "harness:__version__",
    "format": "harness.core.format",
    "transcript": "harness.transcript",
    "approval": "harness.runtime.safety.approval",
    "run_name": "harness.core.episodes:new_name",
    # Agents: the trace a sub-agent of another harness writes; any trace, read.
    "Trace": "harness.core.trace:Trace",
    "read_records": "harness.core.episodes:read_records",
}

__all__ = sorted((*_NAMES, "validate_position"))


def validate_position(arguments, bounds):
    """Compatibility for callers that supply a position mapping."""
    if set(arguments) != {"position"}:
        raise ValueError("Expected a single position field")
    from ..core.codec import validate_vector

    return validate_vector(arguments["position"], bounds)


def __getattr__(name):
    if name not in _NAMES:
        raise AttributeError(f"harness.sdk has no {name!r}; its names are listed in its docstring")
    module, _, attribute = _NAMES[name].partition(":")
    value = importlib.import_module(module)
    if attribute:
        value = getattr(value, attribute)
    globals()[name] = value
    return value


def __dir__():
    return __all__
