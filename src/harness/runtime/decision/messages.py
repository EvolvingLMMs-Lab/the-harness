"""The model's messages: what the conversation (runtime/conversation.py) tells the model
of an embodiment and of each program it ran. The text of each embodiment kind
(EMBODIMENT_TEXT), the state and the camera images of a message, a program's feedback
(its status, output, events, the skills' turn report, the state and steps), another unit's
end, and what a request keeps of the history's images (prune_images, prune_views).
"""

from collections.abc import Mapping
import json

from harness.embodiments import KINDS


# What the model is told about each embodiment kind (embodiments.KINDS): the
# verifier's instructions, the label and keys of the state in every message, and the
# image streams the model sees unless runtime.cameras names others.
# The kinds are the packages' (kinds.toml), read when a kind is first asked for.
class _EmbodimentText(Mapping):
    def __getitem__(self, name):
        kind = KINDS[name]
        return {"verifier": kind.verifier, "state_label": kind.state_label, "state_keys": kind.state_keys,
                "cameras": kind.cameras}

    def __iter__(self):
        return iter(KINDS)

    def __len__(self):
        return len(KINDS)


EMBODIMENT_TEXT = _EmbodimentText()


def image_parts(images: dict, cameras) -> list[dict]:
    """The images of `cameras` among `images`, each after a line with its name."""
    parts = []
    for camera in cameras:
        if camera in images:
            parts.append({"type": "input_text", "text": f"Camera: {camera}"})
            parts.append({"type": "input_image", "image_url": images[camera], "detail": "auto"})
    return parts


def attachment_parts(paths, limit: int = 100_000) -> list[dict]:
    """The files a user attached to a message as content parts, each after a line naming it:
    an image as it is, a folder as its names, any other file as its text (at most `limit`
    characters)."""
    from pathlib import Path

    from harness.core.codec import data_url

    parts = []
    for path in map(Path, paths):
        mime = IMAGE_TYPES.get(path.suffix.lower())
        if path.is_dir():
            names = sorted(child.name + ("/" if child.is_dir() else "") for child in path.iterdir())
            parts.append({"type": "input_text", "text": f"Attached folder {path}:\n" + "\n".join(names[:500])})
        elif mime:
            parts += [{"type": "input_text", "text": f"Attached image {path}:"},
                      {"type": "input_image", "image_url": data_url(path.read_bytes(), mime), "detail": "auto"}]
        else:
            text = path.read_text(encoding="utf-8", errors="replace")
            more = f"\n… {len(text) - limit} more characters" if len(text) > limit else ""
            parts.append({"type": "input_text", "text": f"Attached file {path}:\n{text[:limit]}{more}"})
    return parts


IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif",
               ".webp": "image/webp"}


def state_text(state: dict, embodiment: str = "none", steps: bool = True) -> str:
    """The state the model is shown; without `steps` (a worker that keeps its step budget
    to itself: profile steps_shown false) no step count."""
    keys = [key for key in EMBODIMENT_TEXT[embodiment]["state_keys"] if steps or key != "step"]
    return json.dumps({key: state[key] for key in keys if key in state},
                      default=lambda v: round(v, 4) if isinstance(v, float) else v)


def _round(value):
    if isinstance(value, float):
        return round(value, 4)
    if isinstance(value, list):
        return [_round(item) for item in value]
    if isinstance(value, dict):
        return {key: _round(item) for key, item in value.items()}
    return value


def latest(items, limit: int = 20) -> str:
    """The last `limit` of `items` in one line, after how many earlier ones it leaves out."""
    items = list(items)
    left = len(items) - limit
    return (f"({left} earlier omitted) " if left > 0 else "") + "; ".join(items[-limit:])


def cut(text: str, limit: int) -> str:
    """`text` up to `limit` characters, then how many more there are."""
    return text if len(text) <= limit else text[:limit] + f" ... [{len(text) - limit} more characters]"


def ended_text(result: dict) -> str:
    """The end report of a unit in words: how it ended, and whether what it was for is the
    case ("done": its completion condition held at the end; nothing where it stated none),
    with its seconds. The same for a program of the model, code it spawned and a reflex's
    program."""
    how = result.get("ended") or {"ok": "by itself", "error": "an error"}.get(result["status"], result["status"])
    done = result.get("done")
    return (f"ended: {how}" + ("" if done is None else "; done: yes" if done else "; done: no (what it was for is not the case)")
            + f" ({result.get('seconds', 0):.1f} s)")


# The last line of a message about a reflex: the model is told because it chose to be, when
# it wrote the program or set the node, and this is what it does with the message.
CHOSE_PROGRAM = ("You are told this because you chose to be when you wrote {names}: it matters to that work. Do "
                 "not wait on as before. Compare what {names} reports with what it is for, find out why the "
                 "reflex had to act during it, and decide: it goes on as it is, you change it, or you end it.")
CHOSE_NODE = ("You are told this because you chose to be when you set {name}. Decide what it changes in what you "
              "are doing now.")
CHOSE_STOP = ("{name} ended because you chose so when you wrote it. Find out why the reflex had to act during it, "
              "then decide what is done next.")


def report_parts(name: str, told: dict) -> list[dict]:
    """The pictures and files of what `name` (a node, a program) reports of itself, as the
    parts of a message, each after a line saying whose it is (`told`: {"shows": [{"caption",
    "image_url"}], "files": [{"name", "text"}]}; the text is said with the event)."""
    parts = []
    for item in told.get("shows") or ():
        parts.append({"type": "input_text", "text": f"{name} shows" + (f" {item['caption']}" if item.get("caption") else "") + ":"})
        parts.append({"type": "input_image", "image_url": item["image_url"], "detail": "auto"})
    for item in told.get("files") or ():
        parts.append({"type": "input_text", "text": f"{name} attaches {item['name']}:\n{item['text']}"})
    return parts


def without_pictures(detail):
    """An event's detail as it is recorded: the pictures and files of the reports in it are
    counted, not kept."""
    if not isinstance(detail, dict):
        return detail
    out = {key: value for key, value in detail.items() if key not in ("shows", "files", "interrupted")}
    for key in ("shows", "files"):
        if detail.get(key):
            out[key] = len(detail[key])
    if detail.get("interrupted"):
        out["interrupted"] = [without_pictures(row) for row in detail["interrupted"]]
    return out


def _times(count: int) -> str:
    return "once" if count == 1 else f"{count} times"


def reflex_text(kind: str, detail: dict) -> str:
    """What a node of the tree of reflexes did, as the model reads it: the node with its own
    sentence (`about`), how its program ended, the units it took the environment from (how
    often, for how long), the node's own report (`says`; without one, what its program
    returned), and what each of those units says of itself."""
    name, rows = detail.get("reflex"), detail.get("interrupted") or []
    did = ("did its work" if kind == "REFLEX_ACTED"
           else "ran, and the agent is still in its situation with no other node answering it")
    lines = [f"{name}" + (f" ({detail['about']})" if detail.get("about") else "") + f" {did}: its program ended "
             f"{detail.get('ended')} after {detail.get('seconds', 0):g} s."]
    for row in rows:
        lines.append(f"It took the environment from {row['name']}, {_times(row.get('times') or 1)} so far "
                     f"({row.get('paused_seconds', 0):g} s paused in all); {row['name']} goes on.")
    if detail.get("says") is not None:
        lines.append(f"{name} reports: {detail['says']}")
    elif detail.get("returned") is not None:
        lines.append(f"{name} returned: {detail['returned']}")
    if detail.get("error"):
        lines.append(f"{name} failed: {detail['error']}")
    for row in rows:
        done = "" if row.get("done") is None else "; done: yes" if row["done"] else "; done: no"
        told = (f"reports: {row['says']}" if row.get("says") is not None
                else "reports with what is shown below" if row.get("shows") or row.get("files") else "gives no report")
        lines.append(f"{row['name']} {told} (running {row.get('seconds', 0):g} s{done})")
    # Whose choice it was that the model is told, and what it is told to do with it.
    asked = [row["name"] for row in rows if row.get("asked")]
    if asked:
        lines.append(CHOSE_PROGRAM.format(names=" and ".join(asked)))
    else:
        lines.append(CHOSE_NODE.format(name=name))
    return "\n".join(lines)


def taken_text(detail: dict) -> str:
    """A unit that ended where a unit of higher priority took the environment from it, as
    the model reads it: who took it, with the node's own sentence, from which unit and
    execution, what that unit says of itself, whether it is started again, and the state."""
    who = str(detail.get("rule") or detail.get("by_name") or detail.get("by"))
    name = detail.get("name") or detail.get("unit")
    lines = [f"{who}" + (f" ({detail['about']})" if detail.get("about") else "")
             + f" took the environment from {name}" + (f" during {detail['execution']}" if detail.get("execution") else "")
             + (", which is started again when its turn comes." if detail.get("restart")
                else ", which ended there" + (" as it asked to (until(interrupted=\"stop\"))." if detail.get("asked") else "."))]
    if detail.get("says") is not None or detail.get("done") is not None or detail.get("shows") or detail.get("files"):
        done = "" if detail.get("done") is None else " (done: yes)" if detail["done"] else " (done: no)"
        told = (f"reports: {detail['says']}" if detail.get("says") is not None
                else "reports with what is shown below" if detail.get("shows") or detail.get("files") else "gives no report")
        lines.append(f"{name} {told}{done}")
    if detail.get("state"):
        lines.append(f"State: {detail['state']}")
    if detail.get("asked"):
        lines.append(CHOSE_STOP.format(name=name))
    return "\n".join(lines)


def expected_lines(result: dict) -> list:
    """What a unit expected of the environment (expect(text, check)), one line each with what
    its check showed; and, when all of it held and what the unit was for is not the case,
    that it relied on something it did not check."""
    from harness.runtime.decision.loop import ALL_HELD

    rows = result.get("expected") or []
    lines = [f'Expected "{row["text"]}": ' + ("it held." if row["held"] else f"it does not hold: {row.get('found')}")
             for row in rows]
    if rows and result.get("done") is False and all(row["held"] for row in rows):
        lines.append(ALL_HELD)
    return lines


def cell_feedback(result: dict, number: int) -> str:
    """What the model is told of program `number` it ran: its status, output and error, the
    event that ended it, the executions and the skills' turn report (the state as it is
    now is told once with every call: runtime/task/run.py _ambient). It names the
    program, since programs run side by side and the result of one can reach the model
    after the code of the next."""
    lines = [f"Program {number} " + ended_text(result)]
    lines += expected_lines(result)
    if result.get("says") is not None:
        lines.append("It reports: " + str(result["says"]))
    if result.get("interruptions_untold"):
        lines.append(f"Reflexes took the environment from it {_times(result['interruptions_untold'])} more than you "
                     "were told one by one.")
    if result.get("stdout"):
        lines.append("Output:\n" + result["stdout"].rstrip())
    if result.get("error"):
        lines.append("Error:\n" + result["error"].rstrip())
    trace = result.get("escalation") or result.get("episode_ended")
    if trace:
        event = trace["event"]
        lines.append("Unhandled event: " + json.dumps(_round({
            "kind": event["kind"], "source": event["source"], "detail": event["detail"],
            "skill": trace["skill"], "parameters": trace["parameters"],
            "ticks": trace["end_tick"] - trace["start_tick"]})))
    if result.get("events"):
        executed = [f"{item['skill']}: {item['event']['kind']}" + (" (handled)" if item.get("handled") else "")
                    for item in result["events"]]
        lines.append("Executions: " + latest(executed))
    if result.get("event_counts"):
        lines.append("Execution totals (details in trace): " + json.dumps(result["event_counts"]))
    if (result.get("report") or {}).get("text"):
        lines.append(result["report"]["text"])
    for name, part in (result.get("environments") or {}).items():
        # An environment attached to the conversation (runtime/execution/attached.py).
        if part.get("events"):
            lines.append(f"{name} executions: " + latest(
                f"{item['skill']}: {item['event']['kind']}" + (" (handled)" if item.get("handled") else "")
                for item in part["events"]))
        if part.get("error"):
            lines.append(f"{name}: {part['error']}")
        if part.get("state"):
            lines.append(f"{name} state: " + cut(json.dumps(_round({
                key: value for key, value in part["state"].items()
                if isinstance(value, (str, int, float, bool)) or key in ("screen",)})), 1200))
    return "\n".join(lines)


def unit_feedback(result: dict) -> str:
    """What the model is told of a unit that ended and is not one of its programs (code a
    program spawned, a sub-agent): how it ended, what it printed and returned."""
    lines = [f"Unit {result['unit']} {result.get('name') or ''} ({result.get('kind')}) " + ended_text(result)
             + (" (its failure was handled)" if result.get("handled") else "")]
    lines += expected_lines(result)
    if result.get("stdout"):
        lines.append("Output:\n" + result["stdout"].rstrip())
    if result.get("error"):
        lines.append("Error:\n" + str(result["error"]).rstrip())
    trace = result.get("escalation") or result.get("episode_ended")
    if trace:
        event = trace["event"]
        lines.append("Unhandled event: " + json.dumps(_round({
            "kind": event["kind"], "source": event["source"], "detail": event["detail"], "skill": trace["skill"]})))
    if result.get("returned") is not None:
        returned = result["returned"]
        lines.append("Returned: " + (returned if isinstance(returned, str) else json.dumps(_round(returned), default=str)))
    if result.get("events"):
        lines.append("Executions: " + latest(
            f"{item['skill']}: {item['event']['kind']}" + (" (handled)" if item.get("handled") else "")
            for item in result["events"]))
    return "\n".join(lines)


def unit_text(identifier: str, unit: dict, printed: bool = True) -> str:
    """A running unit as the model hears of it ({"name", "kind", "started"}: runtime/task/run.py),
    and, with `printed`, how long ago it last printed where the host hears a unit's output
    while it runs (its "printed": the time, None for nothing yet)."""
    import time

    now = time.time()
    last = ""
    if printed and "printed" in unit:
        last = (", has printed nothing" if unit["printed"] is None
                else f", last printed {max(0.0, now - unit['printed']):.0f} s ago")
    kept = f", priority {unit['priority']:g}" if unit.get("priority") else ""
    # Which reflexes took the environment from it and gave it back, and how often.
    paused = unit.get("paused_by") or {}
    taken = ("; paused " + ", ".join(f"{count} time{'' if count == 1 else 's'} by {name}"
                                     for name, count in sorted(paused.items(), key=lambda item: -item[1]))
             if paused else "")
    # What it says of itself (until(report=)), as of the state last reported.
    says = f": {unit['says']}" if unit.get("says") is not None else ""
    return (f"{identifier} {unit.get('name') or ''} ({unit.get('kind')}{kept}, "
            f"{max(0.0, now - unit['started']):.0f} s{last}{taken}){says}")


def steps_text(state: dict, hz: float | None) -> str:
    """The env steps used, and left where the episode's limit is reported (Z2 showed both
    every turn): every motion tick counts against the limit."""
    step, limit = int(state["step"]), state.get("step_limit")
    used = f"Env steps used: {step}" + (f" ({hz:g} per second)" if hz else "")
    return used + (f"; left: {int(limit) - step}" if limit else "; the limit is not reported")


def prune_images(messages: list[dict], keep: int) -> None:
    """Keep images only in the last `keep` user messages."""
    seen = 0
    for message in reversed(messages):
        if message["role"] != "user" or isinstance(message["content"], str):
            continue
        if any(part["type"] == "input_image" for part in message["content"]):
            seen += 1
            if seen > keep:
                message["content"] = [part if part["type"] != "input_image"
                                      else {"type": "input_text", "text": "[earlier image omitted]"}
                                      for part in message["content"]]


OMITTED = {"type": "input_text", "text": "[earlier image omitted]"}
# What a model that reads no images gets in place of one.
NOT_SENT = "[image not sent: this model reads no images]"


def view_parts(looks, limit: int = 8) -> list[dict]:
    """The views a program looked at (look, watch: runtime/execution/session.py) as content
    parts: each after a line naming it, its image marked as a view (and with its pin), so
    that prune_views keeps it only as long as the model said."""
    parts = []
    for item in list(looks)[-limit:]:
        where = f" region {item['region']}" if item.get("region") else ""
        pinned = f" (pinned as {item['pin']!r})" if item.get("pin") else ""
        parts.append({"type": "input_text", "text": f"View: {item['camera']}{where}{pinned}"})
        parts.append({"type": "input_image", "image_url": item["image_url"], "detail": "auto",
                      "view": item["camera"], **({"pin": item["pin"]} if item.get("pin") else {})})
    return parts


def prune_views(messages: list[dict], keep: int = 1, pins=(), others: int = 2) -> None:
    """What stays in the history when the model looks on demand. A view is in the model's
    sight for the `keep` replies after the program that looked (1: its next reply only),
    a pinned one while its name is in `pins`; any other image (a file the user attached,
    a show()) stays in the last `others` messages that have one, as prune_images keeps them."""
    turns = seen = 0
    pins = set(pins)
    for message in reversed(messages):
        if message["role"] != "user" or isinstance(message["content"], str):
            continue
        turns += 1
        other = any(part["type"] == "input_image" and "view" not in part for part in message["content"])
        seen += other
        if not any(part["type"] == "input_image" for part in message["content"]):
            continue
        message["content"] = [
            OMITTED if part["type"] == "input_image" and (
                (turns > keep and part.get("pin") not in pins) if "view" in part else seen > others)
            else part for part in message["content"]]


def tokens(message) -> int:
    """About how many tokens a message is: a quarter of its characters, an image as 1200."""
    content = message["content"]
    if isinstance(content, str):
        return len(content) // 4
    return sum(1200 if part["type"] == "input_image" else len(part.get("text") or "") // 4 for part in content)


def recent_start(messages: list[dict], minimum: int, least: int, most: int) -> int:
    """Where the messages begin that a compaction keeps as they are: from the end back
    until they hold `minimum` tokens and `least` messages, or `most` tokens; then on to a
    reply of the model, so that no program is parted from its result. A conversation that
    fits whole keeps its last exchange."""
    total, start = 0, len(messages)
    for index in range(len(messages) - 1, 0, -1):
        total, start = total + tokens(messages[index]), index
        if total >= most or (total >= minimum and len(messages) - index >= least):
            break
    if start <= 1:
        start = max(1, len(messages) - 2)
    while start < len(messages) - 1 and messages[start]["role"] != "assistant":
        start += 1
    return start


def clear_results(messages: list[dict], keep: int, cleared: str) -> int:
    """Replace the results of programs in `messages` (the parts marked "result") by
    `cleared`, but the last `keep`; how many were replaced."""
    seen = replaced = 0
    for message in reversed(messages):
        if message["role"] != "user" or isinstance(message["content"], str):
            continue
        for part in reversed(message["content"]):
            if part.get("result"):
                seen += 1
                if seen > keep and part["text"] != cleared:
                    part["text"], replaced = cleared, replaced + 1
    return replaced


def text_only(messages: list[dict]) -> list[dict]:
    """`messages` for a model that reads no images: each image as a line saying it was not sent."""
    out = []
    for message in messages:
        content = message["content"]
        if not isinstance(content, str) and any(part["type"] == "input_image" for part in content):
            message = {**message, "content": [
                {"type": "input_text", "text": NOT_SENT} if part["type"] == "input_image" else part
                for part in content]}
        out.append(message)
    return out


def content_parts(content) -> list[dict]:
    """A message's content as conversations give it, as the parts the model is sent: a
    string, or a list of parts: text ({"type": "text" | "input_text", "text"}) and images
    ({"type": "image_url", "image_url": url or {"url"}}, {"type": "input_image",
    "image_url"}, or {"type": "image", "source": {"type": "base64", "media_type", "data"}})."""
    if isinstance(content, str):
        return [{"type": "input_text", "text": content}] if content.strip() else []
    parts = []
    for part in content or ():
        if isinstance(part, str):
            parts.append({"type": "input_text", "text": part})
            continue
        kind = part.get("type") if isinstance(part, dict) else None
        if kind in ("text", "input_text") and isinstance(part.get("text"), str):
            parts.append({"type": "input_text", "text": part["text"]})
        elif kind in ("image_url", "input_image"):
            url = part.get("image_url")
            url = url.get("url") if isinstance(url, dict) else url
            if not isinstance(url, str) or not url:
                raise ValueError("an image part gives its image_url")
            parts.append({"type": "input_image", "image_url": url, "detail": part.get("detail") or "auto"})
        elif kind == "image" and isinstance(part.get("source"), dict) and part["source"].get("type") == "base64":
            source = part["source"]
            parts.append({"type": "input_image", "image_url": f"data:{source['media_type']};base64,{source['data']}",
                          "detail": "auto"})
        else:
            raise ValueError(f"a message's content is text and image parts, not {part!r:.80}")
    return parts


def _inbox_parts(pending) -> list[dict]:
    """Messages taken from the inbox as content parts: one text with each message of the
    user or of the agent that started this one, then the files attached to them; then what
    the environment told (TaskRun.tell), each as it gave it."""
    people = [(sender, item, parts) for sender, item, parts in pending if not sender.startswith("environment")]
    told = [(sender, parts) for sender, _, parts in pending if sender.startswith("environment")]
    out = []
    if people:
        text = "\n".join(f"Message from {'the user' if sender == 'user' else 'the agent that started you'}: "
                         + (item or "(the files below)") for sender, item, _ in people)
        out = [{"type": "input_text", "text": text}] + [part for *_, parts in people for part in parts]
    for sender, parts in told:
        out += [{"type": "input_text", "text": f"Message from the {sender}:"}, *parts]
    return out


def rebuild_messages(records) -> list[dict]:
    """The main model's history as the trace has it, up to its last reply: what each
    request added (from the previous reply on, in place of the last messages it
    replaces), less the malformed exchanges dropped after it, and the last reply (but a
    reply to a call made while a program ran that was not used). A compaction replaces
    every message there was (its next request says so). Image pruning is applied per
    request (prune_images, prune_views), so the rebuilt list, pruned the same way, is the
    conversation's own."""
    history, reply = [], None
    for record in records:
        if record["event"] == "model_request":
            if record.get("replaces"):
                del history[len(history) - int(record["replaces"]):]
            history.extend(record["new_messages"])
            reply = None
        elif record["event"] == "model_reply" and record.get("ahead", "used") == "used":
            reply = {"role": "assistant", "content": record["text"]}
        elif record["event"] == "malformed_dropped":
            # The exchanges before the reply that came after them.
            del history[len(history) - int(record["messages"]):]
    return history + ([reply] if reply else [])
