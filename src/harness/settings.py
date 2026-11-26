"""The user's configuration: one file, config.toml in the data directory
(~/.harness/config.toml), with

    [model]        the model chosen (providers.py) and its advanced settings (SCHEMA)
    [keys]         the keys given to the harness (Credentials), readable by the user only
    [packages]     packages.auto_install and packages.registry, the installed packages
                   ([packages.installed.<name>], packages/state.py) and the trusted projects
    [general] ...  the settings the user changes in Settings (SCHEMA), and the sections
                   other modules keep (connectors, skills)

A project adds a harness.toml of its own (its [packages] and harness.lock). The files of
earlier versions (settings.json, model.json, credentials.env, packages.toml) are merged
into config.toml the first time it is read, and no longer read after that.

Each value has a default, a kind and its bounds (SCHEMA); update() takes a section's
changes, checks them and keeps the file. The settings reach a conversation when it
starts (App.config): its budget, its skills (sub-agents while limits.agent_depth allows
them), the model's advanced settings, the user's instructions; a package's settings reach a workspace's worker when it starts, and
its limits (workspaces, chromes, displays) the workspace pool at once; the physical-input
policy and what the model learns of the user's windows are read by the workers each time
they change (a package's sections: its settings.toml).
Settings are changed from the app's page and the terminal chat's /settings.
"""

from collections import namedtuple
from collections.abc import Mapping
import json
import os
from pathlib import Path
import threading
import tomllib

from .config import dumps
from .core import atomic_write


# One setting: `applies` is now, next_conversation or app_start; a list of rules has the fields a
# rule names besides its level ({name: "text", "id", "float" or its choices}), the rule a page
# adds, and any additional fields keyed by level; `system` names what keeps a value that lives in
# the system rather than in config.toml ("module:function", read with no argument, changed with
# the value), such as agent.autostart, which is whether the login item exists. `scope` says
# whose a value is: global (one for this computer), or identity (an agent identity may have its
# own, kept in its folder, over the global one). What a person reads of it is in two languages:
# `title` ({en, zh}), `about` (English) with `about_zh`, and for a choice `labels`
# ({value: {en, zh}}), what each value is called. `shown` false: a key that is read and kept but
# not for a person to see (it has no effect any more, or it only carries what an earlier version
# kept); `advanced`: tuning few people need, which a frontend may fold away.
Setting = namedtuple("Setting", "default kind bounds about applies fields example fields_when system scope title "
                                "about_zh labels shown advanced",
                     defaults=("next_conversation", None, None, None, None, "global", None, None, None, True, False))
# (default, kind, choices or (min, max), what it is[, applies]). Kinds: choice, bool, int,
# float, text, rules (a list of the section's rules, at most max of them, checked by the row's check).
_CORE_SCHEMA = {section: {key: Setting(*row) for key, row in rows.items()} for section, rows in {
    "general": {
        "language": ("system", "choice", ("system", "zh", "en"), "the page's language (system: the browser's)", "now"),
        "theme": ("system", "choice", ("system", "light", "dark"), "light or dark (system: the computer's)", "now"),
        "open_browser": (True, "bool", None, "open the page in the browser when the app starts", "app_start"),
        "notifications": (True, "bool", None, "a notification when the agent asks or finishes, while the page "
                                              "is in the background", "now"),
    },
    "terminal": {
        "editor_mode": ("normal", "choice", ("normal", "vim"),
                        "how the terminal chat's input box is edited: normal (the readline keys) or vim (its "
                        "modes, motions and operators)", "now"),
    },
    "model": {
        "reasoning_effort": ("default", "choice", ("default", "none", "minimal", "low", "medium", "high", "xhigh", "max"),
                             "how much the model reasons before it answers (default: the model's own); a model "
                             "has some of these levels or none, and one it does not have counts as default"),
        "max_output_tokens": (0, "int", (0, 200000), "tokens per reply (0: the harness's default)"),
        "checker": ("", "text", (0, 200), "a model of the same provider that checks the result (empty: the "
                                          "model itself)"),
        "vision": ("", "text", (0, 200), "a model of the same provider that reads images, asked to describe a "
                                         "view when the main model reads none (empty: such a model is told the "
                                         "view was not sent and works from text)"),
        "think_while_acting": ("default", "choice", ("default", "off", "on", "on_events", "periodic"),
                               "accepted for older configurations; it has no effect"),
        "think_interval": (0, "int", (0, 600), "accepted for older configurations"),
    },
    "session": {
        "environment": ("ask", "text", (0, 40),
                        "where a new conversation works when none is named: ask (ask every new conversation, the last "
                        "choice highlighted), last (the last choice again, without asking), or one kind (none, or one "
                        "the installed packages give)", "next_conversation"),
        "agents": ("off", "choice", ("off", "on"),
                   "sub-agents in new conversations: off (their calls and prompt are not loaded; you can switch "
                   "them on in a conversation, and the agent may ask you to), on (loaded from the start, as deep "
                   "as limits.agent_depth allows)"),
    },
    "environments": {
        "attach": ("ask_once_session", "choice", ("never", "ask_each", "ask_once_session", "allow"),
                   "when an agent may take another environment into its conversation (a task that needs "
                   "something only another kind has), where no rule says otherwise: never, ask "
                   "each time, ask once per conversation and kind, allow. Each attachment and its reason is shown "
                   "and recorded whether or not it asked. When you skip confirmations (physical.level allow) it "
                   "does not ask; never still refuses", "now"),
        "rules": ([], "rules", (0, 50),
                  "a level for one environment kind; it wins over "
                  "environments.attach", "now", {"kind": "text"}, {"level": "never", "kind": "KIND"}),
    },
    "approvals": {
        "ask": ("sensitive", "choice", ("sensitive", "programs"),
                "what waits for your approval: sensitive (steps the environment recognizes as touching credentials, "
                "a payment, sending, deleting or what cannot be undone; they always wait; Permissions lists which "
                "environments check) or programs (every program as well)"),
        "programs": ("ask_once_session", "choice", ("never", "ask_each", "ask_once_session", "allow"),
                     "what a program of the agent may do on this computer beyond its own folder (run a command, "
                     "reach the network, write a file elsewhere), where no rule says otherwise: never, ask each "
                     "time, ask once per conversation and kind (a command's program, a host, a folder), allow. "
                     "Reading is not asked about; a file of credentials and deleting always are. When you skip "
                     "confirmations (physical.level allow) it does not ask; never still refuses", "now"),
        "rules": ([], "rules", (0, 200),
                  "a level for one kind of step: action is command, network or write, match a glob on the "
                  "command's program, the host or the folder; it wins over approvals.programs", "now",
                  {"action": "text", "match": "text"}, {"level": "allow", "action": "network", "match": "*.github.com"}),
        "timeout_minutes": (30, "int", (1, 10080),
                            "an approval request left unanswered this long ends as cancelled (never as done)", "now"),
    },
    "instructions": {
        "load": ("all", "choice", ("all", "user", "off"),
                 "the instruction files a new conversation reads (instructions.py): all (yours, "
                 "~/.harness/AGENTS.md, and the project's AGENTS.md from its root down to the folder), user (yours "
                 "only), off (none)"),
        "files": ("AGENTS.override.md, AGENTS.md, CLAUDE.md", "text", (0, 300),
                  "the file names tried in each directory, in order; the first with text is read (a directory's "
                  "CLAUDE.local.md is read after it)"),
        "root_markers": (".git", "text", (0, 300),
                         "what marks a project's root: the nearest folder above holding one of these (comma-separated; "
                         "empty: only the conversation's folder is read)"),
        "max_bytes": (32768, "int", (0, 1048576),
                      "bytes of instructions read at a conversation's start (yours and the project's each); "
                      "what is over it is cut and the model is told how to read the rest (0: yours and the "
                      "project's are not read)"),
        "exclude": ("", "text", (0, 2000), "files never read, as path patterns (comma-separated, e.g. "
                                           "*/vendor/*/AGENTS.md)"),
    },
    "limits": {
        "max_steps": (60, "int", (1, 1000), "model calls a task may take"),
        "max_minutes": (360, "int", (1, 1440), "minutes a conversation may run"),
        "agent_depth": (1, "int", (0, 4), "how deep agents start sub-agents (their budgets come out of the "
                                          "conversation's): 0 none, 1 the conversation's agent does and they do "
                                          "not, 2 theirs do too"),
    },
    "learning": {
        "mode": ("on", "choice", ("on", "review_first", "frozen", "off", "replay_always"),
                 "how an agent identity learns (each identity may set its own): on (new learning takes effect "
                 "at once and can be undone), review_first (it waits for your review), frozen (use what it "
                 "learned without learning), off (nothing learned, and nothing learned loaded); replay_always "
                 "(an advanced option: also recheck eligible entries at the start of ordinary conversations)"),
        "active_minutes": (30, "int", (1, 240), "minutes of live time a \"learn this environment\" conversation "
                                                "takes (the app's Learn, /learn, harness run --learn)"),
        "admission": ("fixture", "choice", ("off", "fixture", "own_test"),
                      "how a skill or reactive rule the agent wrote itself is admitted to a library that learns: "
                      "fixture (only a fixture this computer provides for that entry verifies it; without one "
                      "the proposal waits), own_test (where the environment reports that it is not physical, "
                      "the host also runs the entry's own test between programs; a pass admits it as "
                      "provisional, marked as admitted by its own test, and it goes back to waiting when it "
                      "keeps failing in use; every other environment stays at fixture), off (no learned code "
                      "is admitted or loaded). $HARNESS_LEARNING_ADMISSION wins over it"),
        "review_model": ("", "text", (0, 200),
                         "the model an agent identity's background review and dreaming use: an entry of the model "
                         "list (its ID, or provider/model); empty: the identity's own model", "now"),
    },
    "packages": {
        "auto_install": ("official", "choice", ("official", "ask", "off"),
                         "when a task needs an embodiment, bench, skill or service no installed package provides: "
                         "official (install the registry's package that provides it), ask (ask first), off (stop "
                         "and say which package to install)", "now"),
        "registry": ("", "text", (0, 300), "where packages come from: an https address or a folder of a registry "
                                           "(empty: harness.lmms-lab.com; $HARNESS_REGISTRY wins over it)", "now"),
    },
    "data": {
        "keep_days": (0, "int", (0, 3650), "conversations older than this are deleted when the app starts (0: "
                                           "kept)", "app_start"),
    },
}.items()}

# The core settings an agent identity may have its own value of (the others are one for this computer).
_IDENTITY = (("learning", "mode"), ("learning", "admission"), ("learning", "review_model"))


def _t(en, zh):
    return {"en": en, "zh": zh}


def _labels(*rows):
    return {value: _t(en, zh) for value, en, zh in rows}


_LEVELS = _labels(("never", "Never", "从不"), ("ask_each", "Ask every time", "每次都问"),
                  ("ask_once_session", "Ask once per conversation", "每个对话问一次"), ("allow", "Allow", "允许"))
# What a person reads of each core setting: its title, its description in Chinese (the English
# one is the row's own text) and what each choice is called.
_WORDS = {
    "general.language": (_t("Language", "语言"), "界面的语言（system：跟随浏览器）。",
                         _labels(("system", "Same as the system", "跟随系统"), ("zh", "中文", "中文"),
                                 ("en", "English", "English"))),
    "general.theme": (_t("Appearance", "外观"), "界面的亮暗（system：跟随电脑）。",
                      _labels(("system", "Same as the system", "跟随系统"), ("light", "Light", "亮色"), ("dark", "Dark", "暗色"))),
    "general.open_browser": (_t("Open the page at start", "启动时打开页面"), "app 启动时在浏览器里打开页面。", None),
    "general.notifications": (_t("System notifications", "系统通知"),
                              "只在要你决定或知道的事上发系统通知：等你批准、额度用完、失败或结果不确定、渠道登录过期。", None),
    "terminal.editor_mode": (_t("Editor mode", "编辑模式"), "终端聊天的输入框怎么编辑：普通（readline 的按键），或 vim（它的模式、移动和操作）。",
                             _labels(("normal", "Normal", "普通"), ("vim", "Vim", "Vim"))),
    "model.reasoning_effort": (_t("Reasoning effort", "思考强度"), "模型每次回答前想得多深：越深越慢、越贵。档位是模型自己有的那几档，"
                               "模型没有的档位按它自己的默认算（default：模型自己的默认）。",
                               _labels(("default", "The model's default", "模型默认"), ("none", "None", "不思考"),
                                       ("minimal", "Minimal", "最少"), ("low", "Low", "低"), ("medium", "Medium", "中"),
                                       ("high", "High", "高"), ("xhigh", "Extra high", "很高"), ("max", "Max", "最高"))),
    "model.max_output_tokens": (_t("Tokens per reply", "每次回复的 token 上限"), "每次回复最多多少 token（0：用默认值）。", None),
    "model.checker": (_t("Checking model", "检查用的模型"), "同一提供商里用来检查结果的模型（空：用主模型自己）。", None),
    "model.vision": (_t("Vision model", "看图用的模型"), "主模型不能看图时，由同一提供商的这个模型描述画面（空：告诉主模型没有画面）。", None),
    "model.think_while_acting": (_t("Think while acting (no longer used)", "边做边想（已不使用）"), "为旧配置保留，没有作用。",
                                 _labels(("default", "Default", "默认"), ("off", "Off", "关"), ("on", "On", "开"),
                                         ("on_events", "On events", "有事件时"), ("periodic", "Periodic", "定时"))),
    "model.think_interval": (_t("Think interval (no longer used)", "思考间隔（已不使用）"), "为旧配置保留，没有作用。", None),
    "session.environment": (_t("Where a new conversation works", "新对话在哪里做事"),
                            "新对话没有指定环境时：ask（每次都问，上次的选择高亮）、last（沿用上次的，不问），或一种环境（none，或已安装的扩展包提供的一种）。", None),
    "session.agents": (_t("Sub-agents", "子 agent"), "新对话里的子 agent：off（不加载，对话里可以再打开）、on（一开始就加载）。",
                       _labels(("off", "Off until switched on", "默认关，需要时打开"), ("on", "On from the start", "一开始就打开"))),
    "environments.attach": (_t("Taking another environment into a conversation", "对话里接入别的环境"),
                            "agent 可不可以把另一种环境接进当前对话（任务需要别的环境才有的东西时）。", _LEVELS),
    "environments.rules": (_t("Rules for single environments", "单个环境的规则"), "给某一种环境单独定的档位，优先于上面的默认。", None),
    "approvals.ask": (_t("What waits for your approval", "哪些事等你批准"),
                      "sensitive：环境认出的敏感步骤（凭据、付款、发送、删除、不可撤回）；programs：再加上每一个程序。",
                      _labels(("sensitive", "Sensitive steps", "敏感步骤"), ("programs", "Every program too", "每个程序也要"))),
    "approvals.programs": (_t("What a program may do outside its folder", "程序在自己文件夹之外能做什么"),
                           "运行命令、联网、写别处的文件。读取不问；凭据文件和删除始终要问。", _LEVELS),
    "approvals.rules": (_t("Rules for single steps", "单种步骤的规则"),
                        "给一种步骤单独定的档位（command、network、write，加上匹配的程序、主机或文件夹），优先于上面的默认。", None),
    "approvals.timeout_minutes": (_t("Approval timeout (minutes)", "等批准的时限（分钟）"), "等批准超过这么久没人回答，就算“取消”，不会当成完成。", None),
    "instructions.load": (_t("Instruction files read", "读哪些指令文件"), "新对话开始时读的指令文件：all（你的和项目的）、user（只读你的）、off（都不读）。",
                          _labels(("all", "Yours and the project's", "你的和项目的"), ("user", "Yours only", "只读你的"), ("off", "None", "都不读"))),
    "instructions.files": (_t("Instruction file names", "指令文件的名字"), "每个目录里按顺序尝试的文件名，用第一个有内容的。", None),
    "instructions.root_markers": (_t("Project root markers", "项目根目录的标志"), "往上找到带这些名字之一的文件夹，就是项目的根（逗号分隔）。", None),
    "instructions.max_bytes": (_t("Bytes of instructions read", "读入指令的字节上限"), "对话开始时读入的指令上限（你的和项目的各算）；超过的截掉，并告诉模型怎么读其余的。", None),
    "instructions.exclude": (_t("Instruction files never read", "不读的指令文件"), "永远不读的文件，写成路径模式（逗号分隔）。", None),
    "limits.max_steps": (_t("Model calls a task may take", "一个任务最多调用几次模型"), "一个任务最多调用几次模型。", None),
    "limits.max_minutes": (_t("Minutes a conversation may run", "一个对话最多运行几分钟"), "一个对话最多运行多少分钟。", None),
    "limits.agent_depth": (_t("Depth of sub-agents", "子 agent 的层数"), "agent 可以往下开几层子 agent：0 不开，1 只有对话的 agent 能开，2 它开的也能再开。", None),
    "learning.mode": (_t("Learning", "学习"), "怎么学：on（马上生效，可以撤销）、review_first（先等你看过）、frozen（只用不学）、off（不学也不加载学到的）。",
                      _labels(("on", "On: takes effect at once", "打开：学了就生效"), ("review_first", "Review first", "先审再用"),
                              ("frozen", "Use, do not learn", "只用不学"), ("off", "Off", "关掉"),
                              ("replay_always", "On, rechecking at every start (advanced)", "打开，并且每次开始都重查（高级）"))),
    "learning.active_minutes": (_t("Minutes of a learning session", "一次练习的分钟数"), "“学这个环境”的对话占用多少分钟。", None),
    "learning.admission": (_t("Admitting what it wrote itself", "它自己写的东西怎么准入"),
                           "fixture：只有这台电脑提供的夹具验证过才准入；own_test：在非物理的环境里，自测通过就先准入；off：不准入也不加载。",
                           _labels(("off", "Nothing is admitted", "都不准入"), ("fixture", "Verified by a fixture here", "由这里的夹具验证"),
                                   ("own_test", "By its own test where nothing is physical", "非物理环境里自测通过"))),
    "learning.review_model": (_t("Model for review and dreaming", "回看和 dreaming 用的模型"), "后台回看和 dreaming 用的模型（模型列表里的一项；空：用这个身份的模型）。", None),
    "packages.auto_install": (_t("Installing packages a task needs", "任务需要的扩展包没装时"),
                              "official：自动装 registry 里提供它的包；ask：先问你；off：停下并说该装哪个。",
                              _labels(("official", "Install the official package", "装官方的包"), ("ask", "Ask first", "先问我"),
                                      ("off", "Stop and say which", "停下并说该装哪个"))),
    "packages.registry": (_t("Package registry", "扩展包来源"), "扩展包从哪里来：一个 https 地址或一个文件夹（空：官方 registry）。", None),
    "data.keep_days": (_t("Days conversations are kept", "对话保留天数"), "比这更早的对话在 app 启动时删除（0：一直保留）。", None),
}


# Core settings that are read and kept but no longer do anything: not shown to a person.
_NOT_SHOWN = ("model.think_while_acting", "model.think_interval")
# Core settings few people need: a frontend may fold them away.
_ADVANCED = ("model.max_output_tokens", "model.checker", "model.vision", "instructions.files",
             "instructions.root_markers", "instructions.max_bytes", "instructions.exclude", "packages.registry",
             "learning.admission", "learning.active_minutes")


def _worded(section, key, spec):
    name = f"{section}.{key}"
    title, about_zh, labels = _WORDS.get(name, (None, None, None))
    return spec._replace(title=title, about_zh=about_zh, labels=labels, shown=name not in _NOT_SHOWN,
                         advanced=name in _ADVANCED, scope="identity" if (section, key) in _IDENTITY else "global")


_CORE_SCHEMA = {section: {key: _worded(section, key, spec) for key, spec in keys.items()}
                for section, keys in _CORE_SCHEMA.items()}


class _Schema(Mapping):
    """The core's sections and those packages add in their settings.toml, one table per
    setting with its default, kind, bounds (choices for a choice) and what it is:

        [kit.speed]
        default = 1.0
        kind = "float"
        bounds = [0.1, 10.0]
        about = "how fast the kit moves"

    with applies, fields, example, fields_when and system as in Setting (a section's applies: its
    rows' default). `scope = "identity"` says that an agent identity may have its own value.
    What a person reads: title = { en = "...", zh = "..." }, about_zh = "...", and for a
    choice labels = { fast = { en = "Fast", zh = "快" }, ... }. shown = false keeps a key out
    of every frontend; advanced = true marks tuning few people need.
    A row may name what checks its value (check = "module:function", returning the value as
    kept or raising ValueError): a list of rules, a text of a form of its own. A package's
    section of a name the core has is left out."""

    def __init__(self, core):
        self._core = core
        self._cache = (None, core)
        self._checks = {}

    @staticmethod
    def _row(row: dict, applies: str) -> Setting:
        bounds = row.get("choices", row.get("bounds"))
        return Setting(row.get("default"), row.get("kind", "text"), tuple(bounds) if bounds is not None else None,
                       row.get("about", ""), row.get("applies", applies), row.get("fields"), row.get("example"),
                       row.get("fields_when"), row.get("system"),
                       "identity" if row.get("scope") == "identity" else "global",
                       row.get("title") if isinstance(row.get("title"), dict) else None,
                       row.get("about_zh"), row.get("labels") if isinstance(row.get("labels"), dict) else None,
                       row.get("shown", True) is not False, row.get("advanced") is True)

    def _sections(self) -> dict:
        from .paths import find

        files = tuple(find("settings.toml"))
        if files != self._cache[0]:
            sections = dict(self._core)
            checks = {}
            for path in files:
                with path.open("rb") as handle:
                    for section, keys in tomllib.load(handle).items():
                        if section in self._core or not isinstance(keys, dict):
                            continue
                        sections[section] = {key: self._row(row, keys.get("applies", "next_conversation"))
                                             for key, row in keys.items() if isinstance(row, dict)}
                        checks.update({(section, key): row["check"] for key, row in keys.items()
                                       if isinstance(row, dict) and row.get("check")})
            self._cache, self._checks = (files, sections), checks
        return self._cache[1]

    def __getitem__(self, section):
        return self._sections()[section]

    def checker(self, section: str, key: str):
        """The function that checks section.key's value, when its row names one."""
        import importlib

        self._sections()
        reference = self._checks.get((section, key))
        if reference is None:
            return None
        module, _, attribute = reference.partition(":")
        return getattr(importlib.import_module(module), attribute)

    def __iter__(self):
        return iter(self._sections())

    def __len__(self):
        return len(self._sections())


SCHEMA = _Schema(_CORE_SCHEMA)


# The configuration file, and the files of earlier versions merged into it once.
FILE = "config.toml"
OLD_FILES = ("settings.json", "model.json", "credentials.env", "packages.toml")
# The app's provider key.
KEY = "OPENROUTER_API_KEY"
COMMENT = "The Harness: your configuration (/settings in harness, the app's Settings)."
# Not settings: never in get(), never written by put() ([model] is a SCHEMA section too).
PRIVATE = ("model", "keys")


def defaults() -> dict:
    return {section: {key: (list(spec[0]) if isinstance(spec[0], list) else spec[0]) for key, spec in keys.items()}
            for section, keys in SCHEMA.items()}


def check(section: str, key: str, value):
    """`value` for section.key as its kind takes it, or ValueError."""
    if section not in SCHEMA or key not in SCHEMA[section]:
        raise ValueError(f"no setting {section}.{key}")
    kind, bounds = SCHEMA[section][key].kind, SCHEMA[section][key].bounds
    checker = SCHEMA.checker(section, key) or _CORE_CHECKS.get((section, key))
    if checker is not None and kind != "rules":
        try:
            return checker(value)
        except ValueError as error:
            raise ValueError(f"{section}.{key}: {error}") from None
    if kind == "choice":
        if value not in bounds:
            raise ValueError(f"{section}.{key} is one of {', '.join(bounds)}")
        return value
    if kind == "bool":
        if not isinstance(value, bool):
            raise ValueError(f"{section}.{key} is true or false")
        return value
    if kind == "rules":
        if not isinstance(value, (list, tuple)):
            raise ValueError(f"{section}.{key} is a list of rules")
        if len(value) > bounds[1]:
            raise ValueError(f"{section}.{key} has at most {bounds[1]} rules")
        if checker is None:
            raise ValueError(f"{section}.{key}: nothing checks its rules here")
        try:
            return checker(value)
        except ValueError as error:
            raise ValueError(f"{section}.{key}: {error}") from None
    if kind in ("int", "float"):
        if isinstance(value, bool):
            raise ValueError(f"{section}.{key} is a number")
        try:
            number = int(value) if kind == "int" else float(value)
        except (TypeError, ValueError):
            raise ValueError(f"{section}.{key} is a number") from None
        if kind == "int" and float(value) != number:
            raise ValueError(f"{section}.{key} is a whole number")
        low, high = bounds
        if not low <= number <= high:
            raise ValueError(f"{section}.{key} is between {low} and {high}")
        return number
    text = str(value if value is not None else "").strip()
    if len(text) > bounds[1]:
        raise ValueError(f"{section}.{key} has at most {bounds[1]} characters")
    return text


def _environment(value):
    """session.environment: ask, last, or the name of a workspace kind (checked against the
    installed packages when a conversation starts)."""
    import re

    text = str(value if value is not None else "").strip()
    if not re.fullmatch(r"[a-z][a-z0-9_-]{0,39}", text):
        raise ValueError("ask, last, or a workspace kind (none, or one the installed packages give)")
    return text


def _attach_rules(value):
    """environments.rules: each {"level": one of environments.attach's, "kind": a workspace kind},
    one rule per kind."""
    levels = _CORE_SCHEMA["environments"]["attach"].bounds
    rules, seen = [], set()
    for row in value:
        if not isinstance(row, dict) or set(row) != {"level", "kind"}:
            raise ValueError("a rule is {level, kind}")
        kind = _environment(row["kind"])
        if row["level"] not in levels:
            raise ValueError(f"a rule's level is one of {', '.join(levels)}")
        if kind in ("ask", "last", "none") or kind in seen:
            raise ValueError(f"one rule for each workspace kind; {kind!r} cannot have one here")
        seen.add(kind)
        rules.append({"level": row["level"], "kind": kind})
    return rules


# What checks a core setting whose kind's own check is not enough.
def _program_rules(value):
    from harness.runtime.safety.permissions import rules

    return rules(value)


_CORE_CHECKS = {("session", "environment"): _environment, ("environments", "rules"): _attach_rules,
                ("approvals", "rules"): _program_rules}


# One change at a time in this process (the page's requests come on threads of their own).
_WRITING = threading.RLock()


def path(directory) -> Path:
    return Path(directory) / FILE


def read(directory) -> dict:
    """The whole configuration file ({} when there is none), the files of earlier
    versions merged into it first."""
    file = path(directory)
    if not file.is_file() and any((Path(directory) / name).is_file() for name in OLD_FILES):
        with _WRITING:
            if not file.is_file():
                write(directory, _merged_old(Path(directory)))
    try:
        with file.open("rb") as handle:
            data = tomllib.load(handle)
    except FileNotFoundError:
        return {}
    except UnicodeError:
        raise ValueError(f"{file}: invalid UTF-8; correct the configuration before saving changes") from None
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise ValueError(f"{file}: {error}; correct the configuration before saving changes") from None
    return data


def write(directory, data: dict) -> None:
    """Keep the whole configuration file (readable by the user only: it holds keys)."""
    atomic_write(path(directory), dumps(data, COMMENT), private=True)


def change(directory, function) -> dict:
    """Read the file, let `function` change the data in place, keep it; returns the data."""
    with _WRITING:
        data = read(directory)
        function(data)
        write(directory, data)
        return data


def env_file(path) -> dict:
    """NAME=value (or `export NAME=value`) lines of an env file ({} when there is none)."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return {}
    values = {}
    for line in text.splitlines():
        name, sep, value = line.strip().removeprefix("export ").partition("=")
        if sep and name.strip().isidentifier():
            values[name.strip()] = value.strip().strip("\"'")
    return values


class Credentials:
    """The providers' keys (providers.KEY_NAMES), loaded here only: from the environment or
    [keys] of the user's config.toml (put into this process's environment on load); a key
    given in a frontend goes to [keys] (the file is readable by the user only)."""

    def __init__(self, directory: Path, names=None):
        from .providers import KEY_NAMES

        self.directory = Path(directory)
        self.file = path(directory)
        self.names = list(names or KEY_NAMES)
        self.sources = {}

    @property
    def source(self):
        return self.sources.get(KEY)

    def _kept(self) -> dict:
        return {str(name): str(value) for name, value in (read(self.directory).get("keys") or {}).items()}

    def load(self) -> None:
        kept = self._kept()
        for name in self.names:
            if os.environ.get(name):
                self.sources[name] = "environment"
                continue
            if kept.get(name):
                os.environ[name] = kept[name]
                self.sources[name] = str(self.file)

    def status(self, name: str = KEY) -> dict:
        return {"set": bool(os.environ.get(name)), "source": self.sources.get(name), "name": name}

    def save(self, value: str, name: str = KEY) -> None:
        value = value.strip()
        self.keep(name, value)
        os.environ[name] = value
        self.sources[name] = str(self.file)

    def secret(self, name: str) -> str | None:
        """A secret kept for a connector (only in [keys]: never put into the
        environment, so no process the app starts inherits it)."""
        return self._kept().get(name) or None

    def keep(self, name: str, value: str | None) -> None:
        """Persist a key in [keys] of config.toml (None removes it), leaving the process
        environment and provider source tracking unchanged."""
        def apply(data):
            keys = data.setdefault("keys", {})
            if value is None:
                keys.pop(name, None)
            else:
                keys[name] = str(value).strip()

        change(self.directory, apply)


def _merged_old(directory: Path) -> dict:
    """settings.json, model.json, credentials.env and packages.toml as one configuration."""
    data = {}
    try:
        old = json.loads((directory / "settings.json").read_text(encoding="utf-8"))
        data.update({key: value for key, value in old.items() if key != "keys"})
    except (OSError, ValueError, AttributeError):
        pass
    try:
        model = json.loads((directory / "model.json").read_text(encoding="utf-8"))
        if isinstance(model, dict):
            data.setdefault("model", {}).update({key: value for key, value in model.items() if value is not None})
    except (OSError, ValueError):
        pass
    keys = env_file(directory / "credentials.env")
    if keys:
        data["keys"] = keys
    try:
        with (directory / "packages.toml").open("rb") as handle:
            packages = tomllib.load(handle)
        section = data.setdefault("packages", {})
        section["installed"] = packages.get("packages", {})
        section["trusted_projects"] = packages.get("trusted_projects", [])
        section["addons_migrated"] = bool(packages.get("migrated", False))
    except (OSError, tomllib.TOMLDecodeError):
        pass
    return data


class ChoiceRequired(ValueError):
    """A user preference is unset; no task has started and no value was selected."""

    def __init__(self, choice):
        self.choice = choice
        super().__init__(choice.get("message")
                         or f"Choose {choice['section']}.{choice['key']} before using this capability")


class Settings:
    """The settings in config.toml (FILE) of a data directory, over the defaults.
    Sections other modules keep (connectors, skills) are stored as they give them."""

    def __init__(self, directory: Path):
        self.directory = Path(directory)
        self.file = path(directory)

    def _read(self) -> dict:
        return read(self.directory)

    def require_choice(self, section, key, *, title, options, override=None):
        """Use an explicit valid value, never a schema default, for a user decision."""
        value = override if override is not None else self._read().get(section, {}).get(key)
        if value is not None:
            try:
                value = check(section, key, value)
                if any(option['value'] == value for option in options):
                    return value
            except ValueError:
                pass
        raise ChoiceRequired({"section": section, "key": key, "title": title, "options": options})

    def remembered(self, section, key):
        """What the harness itself kept under section.key (remember), or None: state beside
        the settings (the last environment a conversation chose), never a setting."""
        return (self._read().get(section) or {}).get(key)

    def remember(self, section, key, value) -> None:
        """Keep `value` under section.key for remembered() (None forgets it)."""
        if key in SCHEMA.get(section, {}):
            raise ValueError(f"{section}.{key} is a setting; use update()")

        def apply(saved):
            if value is None:
                saved.get(section, {}).pop(key, None)
            else:
                saved.setdefault(section, {})[key] = value

        change(self.directory, apply)

    def get(self) -> dict:
        """Every setting: the saved ones, the defaults for the rest (a saved value that no
        longer checks falls back to its default)."""
        saved = self._read()
        # limits.ask_before_acting (before 1.0) is approvals.ask = "programs".
        if (saved.get("limits") or {}).get("ask_before_acting") is True and "ask" not in (saved.get("approvals") or {}):
            saved.setdefault("approvals", {})["ask"] = "programs"
        values = defaults()
        for section, keys in SCHEMA.items():
            for key in keys:
                if key in (saved.get(section) or {}):
                    try:
                        values[section][key] = check(section, key, saved[section][key])
                    except ValueError:
                        pass
        for section, value in saved.items():
            if section not in SCHEMA and section not in PRIVATE:
                values[section] = value
        for section, keys in SCHEMA.items():
            for key, spec in keys.items():
                if spec.system:
                    # A value the system keeps (the login item): when the system cannot be
                    # asked, the setting's default, never an error for every other setting.
                    try:
                        values[section][key] = _system(spec.system)()
                    except Exception:
                        values[section][key] = spec.default
        return values

    def update(self, changes: dict) -> dict:
        """Apply {section: {key: value}} (every value checked first) and keep the file."""
        if not isinstance(changes, dict):
            raise ValueError("send {section: {key: value}}")
        checked = {}
        for section, values in changes.items():
            if not isinstance(values, dict):
                raise ValueError(f"{section}: send {{key: value}}")
            checked[section] = {key: check(section, key, value) for key, value in values.items()}
        for section, values in checked.items():
            for key in [key for key in values if SCHEMA[section][key].system]:
                _system(SCHEMA[section][key].system)(values.pop(key))

        def apply(saved):
            for section, values in checked.items():
                saved.setdefault(section, {}).update(values)

        change(self.directory, apply)
        return self.get()

    def reset(self, section: str, key: str) -> dict:
        """Forget the saved value of section.key: its default holds again. Every setting after it."""
        if section not in SCHEMA or key not in SCHEMA[section]:
            raise ValueError(f"no setting {section}.{key}")
        if SCHEMA[section][key].system:
            raise ValueError(f"{section}.{key} is kept by the system, not in the configuration: set it instead")

        def apply(saved):
            (saved.get(section) or {}).pop(key, None)
            if section in saved and not saved[section]:
                del saved[section]

        change(self.directory, apply)
        return self.get()

    def put(self, section: str, value) -> None:
        """Keep a section another module owns (connectors, skills) as it is."""
        if section in SCHEMA or section in PRIVATE:
            raise ValueError(f"{section} is not kept by put()")
        change(self.directory, lambda saved: saved.__setitem__(section, value))


def _system(reference: str):
    """The function a setting's `system` names."""
    import importlib

    module, _, attribute = reference.partition(":")
    return getattr(importlib.import_module(module), attribute)


def describe(section: str, key: str, spec: Setting) -> dict:
    """One setting as a frontend draws it: the Setting's own fields, and

        name         section.key, the name it has everywhere (config, the API, the command line)
        title        {en, zh}: what it is called
        about        {en, zh}: what it is (`description` is the same)
        type         its kind: choice, bool, int, float, text or rules
        choices      for a choice, its values in order (as `bounds`); else None
        labels       for a choice, {value: {en, zh}}: what each value is called
        options      for a choice, [{value, en, zh}]: the two together
        scope        global, or identity (an agent identity may have its own value)
        shown        false for a key no frontend shows a person (it does nothing any more, or
                     only carries what an earlier version kept)
        advanced     true for tuning few people need: a frontend may fold it away

    A setting whose package gives no title is called by its key's words; a choice without a
    label, by its value."""
    words = key.replace("_", " ")
    plain = {"en": words[:1].upper() + words[1:], "zh": words[:1].upper() + words[1:]}
    title = {**plain, **{lang: str(text) for lang, text in (spec.title or {}).items() if text}}
    if "zh" not in (spec.title or {}):
        title["zh"] = title["en"]
    choices = options = labels = None
    if spec.kind == "choice":
        given = spec.labels or {}
        choices, options, labels = list(spec.bounds or ()), [], {}
        for value in choices:
            label = given.get(value) if isinstance(given.get(value), dict) else {}
            en = str(label.get("en") or str(value).replace("_", " "))
            labels[value] = {"en": en, "zh": str(label.get("zh") or en)}
            options.append({"value": value, **labels[value]})
    about = {"en": spec.about, "zh": spec.about_zh or spec.about}
    return {**spec._asdict(), "name": f"{section}.{key}", "title": title, "about": about, "description": about,
            "type": spec.kind, "choices": choices, "labels": labels, "options": options}


def described() -> dict:
    """The schema as the pages read it: {section: {key: describe()}}."""
    return {section: {key: describe(section, key, spec) for key, spec in keys.items()}
            for section, keys in SCHEMA.items()}


def split(name: str) -> tuple:
    """(section, key) of a setting's name section.key; a ValueError says that there is none."""
    section, dot, key = str(name or "").partition(".")
    if not dot or section not in SCHEMA or key not in SCHEMA[section]:
        import difflib

        known = [f"{s}.{k}" for s, keys in SCHEMA.items() for k in keys]
        near = difflib.get_close_matches(str(name), known, n=1)
        raise ValueError(f"no setting {name}" + (f" (did you mean {near[0]}?)" if near else ""))
    return section, key


def rows(values: dict) -> list[dict]:
    """Every setting as a row of a list (the terminal chat's /settings, the app's Settings)."""
    return [{"setting": f"{section}.{key}", "section": section, "key": key, "kind": spec.kind,
             "value": values.get(section, {}).get(key, spec.default), "applies": spec.applies, "about": spec.about,
             "scope": spec.scope, "shown": spec.shown, "advanced": spec.advanced}
            for section, keys in SCHEMA.items() for key, spec in keys.items()]


def rule_fields(section: str) -> dict:
    """The fields a rule of `section` names besides its level; {} when it has no rules."""
    return next((dict(spec.fields or {}) for spec in SCHEMA.get(section, {}).values() if spec.kind == "rules"), {})

