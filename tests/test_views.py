"""Views reach the model only when the model looks, and stay as long as it says; a model
that reads no images is sent none; a configuration that declares runtime.cameras keeps its
standing watch exactly as before."""
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest import mock

import helpers  # noqa: F401
from harness import model_list, providers
from harness.config.agent import TaskConfig
from harness.core.worker import create_server
from harness.runtime.decision.messages import (NOT_SENT, OMITTED, prune_images, prune_views, text_only,
                                               view_parts)
from harness.runtime.decision.model import ScriptedChat
from harness.runtime.decision.prompts import assemble_prompt, features_for
from harness.runtime.task.run import TaskRun

from view_fixtures import ScreenEnvironment

FIXTURES = os.pathsep.join([str(Path(__file__).resolve().parent), os.environ.get("PYTHONPATH", "")])
ROOT = Path(__file__).resolve().parents[1]


def images(message) -> list:
    content = message["content"]
    return [] if isinstance(content, str) else [part for part in content if part.get("type") == "input_image"]


def texts(message) -> str:
    content = message["content"]
    return content if isinstance(content, str) else "\n".join(part.get("text", "") for part in content)


class Recording(ScriptedChat):
    def __init__(self, replies):
        super().__init__(replies)
        self.requests = []

    def complete(self, system, messages):
        self.requests.append((system, json.loads(json.dumps(messages))))
        return super().complete(system, messages)


def episode(replies, *, runtime=None, main=None, verifier=None, seconds=0.0):
    """One episode on the screen worker: (the model's requests, the trace records, the worker)."""
    environment = ScreenEnvironment(seconds)
    worker = create_server(environment, port=0)
    threading.Thread(target=worker.serve_forever, daemon=True).start()
    chat = Recording(replies)
    with tempfile.TemporaryDirectory() as root:
        try:
            config = TaskConfig(
                path=Path("."), environment={"endpoint": f"http://127.0.0.1:{worker.server_address[1]}"},
                main={"model": "scripted", **(main or {})}, system_prompt="You act by writing programs.",
                runtime={"bootstrap": "view_fixtures:screen_session", "verifier": verifier is not None,
                         "isolation": False, "skills": ["desktop"], "purpose": "optional",
                         "reflex_method": "optional", **(runtime or {})},
                task="free", seeds=[0], max_model_calls=12, max_wall_seconds=120, embodiment="desktop")
            with mock.patch.dict(os.environ, {"PYTHONPATH": FIXTURES}):
                summary = TaskRun(config, 0, Path(root) / "seed-0", chat=chat, verifier=verifier).run()
            records = [json.loads(line) for line in
                       (Path(root) / "seed-0" / "events.jsonl").read_text(encoding="utf-8").splitlines()]
        finally:
            worker.shutdown()
            worker.server_close()
    return chat.requests, records, environment, summary


def program(body):
    return f"<python>\n{body}\n</python>"


class OnDemandViewTests(unittest.TestCase):
    def test_no_image_reaches_the_model_unless_a_program_looks(self):
        requests, records, worker, summary = episode([
            program("type_text(2)\nprint('typed', get_state()['step'])"),
            program("type_text(1)"), "<finish>done</finish>"])
        self.assertEqual(summary["status"], "finished", summary)
        for _, messages in requests:
            self.assertEqual([part for message in messages for part in images(message)], [])
        # The opening message names the views and how to get one; the worker was never
        # asked for a picture.
        opening = texts(requests[0][1][0])
        self.assertIn("Views of this environment: screen", opening)
        self.assertIn("look()", opening)
        self.assertEqual(worker.observed, 0)
        self.assertIn("typed 2", texts(requests[1][1][-1]))
        self.assertIn("Computer state", texts(requests[1][1][-1]))
        for record in records:
            if record["event"] == "model_request":
                self.assertEqual(sum(row["images"] for row in record["context"]), 0)

    def test_look_brings_the_view_with_that_programs_result_for_one_reply(self):
        requests, records, worker, _ = episode([
            program("type_text(3)\nseen = look()\nprint(seen)"),
            program("type_text(1)"), "<finish>done</finish>"])
        # Acting and looking were one model call: the picture is the one after the typing.
        self.assertEqual(worker.observed, 1)
        after = requests[1][1][-1]
        self.assertEqual(len(images(after)), 1)
        self.assertIn("View: screen", texts(after))
        from view_fixtures import picture

        self.assertEqual(images(after)[0]["image_url"], picture(shade=3))
        # It stays for that reply only: the next request has it no more.
        self.assertEqual([part for message in requests[2][1] for part in images(message)], [])
        self.assertIn(OMITTED["text"], "\n".join(texts(message) for message in requests[2][1]))
        looked = next(record for record in records if record["event"] == "views" and record["action"] == "looked")
        self.assertEqual(looked["views"], [{"camera": "screen"}])

    def test_keep_and_pin_are_the_models_to_say(self):
        requests, _, _, _ = episode([
            program("look(keep=2)"), program("look(pin='before')"), program("type_text(1)"),
            program("unpin('before')\ntype_text(1)"), program("type_text(1)"), "<finish>done</finish>"])
        count = [sum(len(images(message)) for message in messages) for _, messages in requests]
        # 1: after the first look. 2: it is within keep=2, with the pinned one. 1: the first is
        # two programs old and gone, the pinned one stays. 0: unpinned and past keep.
        self.assertEqual(count, [0, 1, 2, 1, 0, 0])

    def test_region_is_a_part_of_the_view(self):
        import cv2
        import numpy as np
        from harness.core.codec import decode_data_url
        from harness.runtime.execution.session import _cropped
        from view_fixtures import picture

        part = _cropped(picture(shade=3), [2, 1, 4, 3], "png")
        image = cv2.imdecode(np.frombuffer(decode_data_url(part), dtype=np.uint8), cv2.IMREAD_COLOR)
        self.assertEqual(image.shape[:2], (3, 4))
        with self.assertRaisesRegex(ValueError, "outside the view"):
            _cropped(picture(), [50, 50, 4, 3], "png")
        parts = view_parts([{"camera": "screen", "image_url": part, "region": [2, 1, 4, 3]}])
        self.assertIn("region [2, 1, 4, 3]", parts[0]["text"])

    def test_watch_is_turned_on_by_the_model_and_ends_with_unwatch(self):
        requests, records, worker, _ = episode([
            program("print(watch())\ntype_text(1)"), program("type_text(1)"),
            program("print(unwatch())\ntype_text(1)"), program("type_text(1)"), "<finish>done</finish>"])
        count = [len(images(messages[-1])) for _, messages in requests]
        self.assertEqual(count, [0, 1, 1, 0, 0])
        self.assertEqual(worker.observed, 2)
        actions = [record["action"] for record in records if record["event"] == "views"]
        self.assertEqual([action for action in actions if action != "looked"], ["watch", "unwatch"])

    def test_a_node_that_stops_ends_what_runs(self):
        requests, _, _, _ = episode([
            program("set_reflex('too_far', lambda view: view['step'] > 1, 'stop')\n"
                    "r = type_text(5)\nprint('not reached')"), "<finish>done</finish>"])
        told = texts(requests[1][1][-1])
        self.assertIn("GUARD_TRIGGERED", told)
        self.assertIn("too_far", told)
        self.assertNotIn("not reached", told)
        self.assertEqual(images(requests[1][1][-1]), [])

    def test_the_verifier_gets_state_structure_and_views(self):
        verifier = Recording(["YES the body says hello world"])
        requests, _, _, _ = episode(["<verify>the body says hello world</verify>", "<finish>done</finish>"],
                                    verifier=verifier)
        system, messages = verifier.requests[0]
        evidence = texts(messages[0])
        self.assertIn("Claim: the body says hello world", evidence)
        self.assertIn("Computer state", evidence)
        self.assertIn('e1 edit "Body" value "hello world"', evidence)
        self.assertEqual(len(images(messages[0])), 1)
        self.assertIn("what the environment reports as text", system)
        # The model is told the answer in text; the verifier's pictures are not pushed on it.
        answered = requests[1][1][-1]
        self.assertIn("Verifier: YES", texts(answered))
        self.assertEqual(images(answered), [])


class TextOnlyModelTests(unittest.TestCase):
    def test_a_model_that_reads_no_images_is_sent_none(self):
        requests, records, _, summary = episode([program("type_text(1)\nlook()"), "<finish>done</finish>"],
                                                main={"images": False})
        self.assertEqual(summary["status"], "finished", summary)
        for _, messages in requests:
            self.assertEqual([part for message in messages for part in images(message)], [])
        told = texts(requests[1][1][-1])
        self.assertIn("View: screen: not sent", told)
        self.assertIn("reads no images", told)
        for record in records:
            if record["event"] == "model_request":
                self.assertEqual(sum(row["images"] for row in record["context"]), 0)

    def test_a_vision_model_describes_the_view_instead(self):
        seen = []

        class Viewer:
            def __init__(self, config, transport=None):
                self.model = config["model"]

            def complete(self, system, messages, **options):
                from harness.runtime.decision.model import ChatReply

                seen.append((self.model, system, messages))
                return ChatReply("A text editor; its body reads: hello")

        with mock.patch("harness.runtime.decision.model.ChatModel", Viewer):
            requests, _, _, _ = episode([program("look()"), "<finish>done</finish>"], main={"images": False},
                                        runtime={"viewer": {"model": "sees-images", "backend": "openrouter"}})
        told = texts(requests[1][1][-1])
        self.assertIn("as the vision model describes it", told)
        self.assertIn("its body reads: hello", told)
        self.assertEqual(images(requests[1][1][-1]), [])
        self.assertEqual(seen[0][0], "sees-images")
        self.assertEqual(len(images(seen[0][2][0])), 1)

    def test_text_only_strips_attached_files_too(self):
        messages = [{"role": "user", "content": [{"type": "input_text", "text": "see this"},
                                                 {"type": "input_image", "image_url": "data:x", "detail": "auto"}]},
                    {"role": "assistant", "content": "ok"}]
        stripped = text_only(messages)
        self.assertEqual(stripped[0]["content"][1], {"type": "input_text", "text": NOT_SENT})
        self.assertEqual(stripped[1], messages[1])
        self.assertEqual(messages[0]["content"][1]["type"], "input_image")  # the history keeps it

    def test_the_flag_lives_in_the_model_list_and_reaches_the_role(self):
        with tempfile.TemporaryDirectory() as root, \
                mock.patch.dict(os.environ, {"HARNESS_DATA": root, "OPENROUTER_API_KEY": "test-no-network"}):
            directory = Path(root)
            choice = {"provider": "openrouter", "model": "acme/text-only", "base_url": None}
            self.assertTrue(model_list.reads_images(directory, choice))  # unknown: it reads them
            rows = model_list.models(directory, {"action": "save", **choice, "images": False})
            self.assertIs(rows[-1]["images"], False)
            self.assertFalse(model_list.reads_images(directory, choice))
            self.assertIs(json.loads((directory / "models.json").read_text(encoding="utf-8"))[-1]["images"], False)
            # The user may change it; the entry is the same one.
            again = model_list.models(directory, {"action": "save", **choice, "images": True, "id": rows[-1]["id"]})
            self.assertEqual((len(again), again[-1]["images"]), (len(rows), True))
            with self.assertRaises(ValueError):
                model_list.entry({**choice, "images": "no"})
            role = providers.model_role(choice, {"images": False})
            self.assertIs(role["images"], False)
            self.assertNotIn("images", providers.model_role(choice, {}))
            self.assertIsNone(providers.viewer_role(choice, {"images": False}))
            self.assertIsNone(providers.viewer_role(choice, {"vision": "acme/sees"}))
            self.assertEqual(providers.viewer_role(choice, {"images": False, "vision": "acme/sees"})["model"],
                             "acme/sees")

    def test_the_catalog_says_which_models_read_images(self):
        listing = {"data": [{"id": "a/sees", "architecture": {"input_modalities": ["text", "image"]}},
                            {"id": "a/reads", "architecture": {"input_modalities": ["text"]}},
                            {"id": "a/unknown"}]}

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def read(self):
                return json.dumps(listing).encode()

        with tempfile.TemporaryDirectory() as root, mock.patch("harness.providers.open_url", return_value=Response()), \
                mock.patch("harness.providers.json.load", return_value=listing):
            found = {row["id"]: row for row in providers.catalog(Path(root), "openrouter")}
        self.assertIs(found["a/sees"]["images"], True)
        self.assertIs(found["a/reads"]["images"], False)
        self.assertNotIn("images", found["a/unknown"])

    def test_the_environment_choice_says_so_beside_the_screens(self):
        from harness.host.tasks import TaskHost

        with tempfile.TemporaryDirectory() as root, \
                mock.patch.dict(os.environ, {"HARNESS_DATA": root, "OPENROUTER_API_KEY": "test-no-network"}):
            app = TaskHost(Path(root))
            try:
                self.assertTrue(all("note" not in row for row in app.environments()["options"]))
                choice = providers.load(app.directory)
                app.models({"action": "save", **choice, "images": False})
                by = {row["value"]: row for row in app.environments()["options"]}
                self.assertIn("needs a model that reads images", by["desktop"]["note"])
                self.assertIn("needs a model that reads images", by["browser"]["note"])
                self.assertNotIn("note", by["project"])
                self.assertNotIn("note", by["none"])
                from harness.settings import ChoiceRequired

                with self.assertRaises(ChoiceRequired) as asked:
                    app.environment()
                labels = {row["value"]: row["label"] for row in asked.exception.choice["options"]}
                self.assertIn("reads none", labels["desktop"])
                self.assertNotIn("reads none", labels["project"])
                # The conversation's own configuration: no image for its model, a viewer when set.
                config = app.config(None, "none")
                self.assertIs(config.main["images"], False)
                self.assertNotIn("viewer", config.runtime)
                app.settings.update({"model": {"vision": "acme/sees"}})
                self.assertEqual(app.config(None, "none").runtime["viewer"]["model"], "acme/sees")
                self.assertIn("acme/sees describes", app.environments()["options"][-1].get("note", "")
                              or {row["value"]: row for row in app.environments()["options"]}["desktop"]["note"])
            finally:
                app.close()


class StandingWatchTests(unittest.TestCase):
    """runtime.cameras declares the watch: the evaluation configurations' observation is as before."""

    def test_declared_cameras_come_with_every_turn_as_before(self):
        requests, records, worker, _ = episode([
            program("type_text(1)\nprint(sorted(name for name in ('look', 'unwatch', 'unpin') if name in globals()))"),
            program("type_text(1)"), program("type_text(1)"), program("type_text(1)"), "<finish>done</finish>"],
            runtime={"cameras": ["screen"], "keep_images": 2})
        # The opening message carries the reset's picture; every program's result the screen.
        self.assertEqual(len(images(requests[0][1][0])), 1)
        self.assertNotIn("Views of this environment", texts(requests[0][1][0]))
        self.assertEqual([len(images(messages[-1])) for _, messages in requests], [1, 1, 1, 1, 1])
        self.assertIn("Camera: screen", texts(requests[1][1][-1]))
        # keep_images counts the turns with pictures, as it did.
        self.assertEqual([sum(len(images(message)) for message in messages) for _, messages in requests],
                         [1, 2, 2, 2, 2])
        # Programs get none of the on-demand calls: their namespace is the one they had.
        self.assertIn("[]", texts(requests[1][1][-1]))
        self.assertEqual(worker.observed, 4)
        self.assertFalse(any(record["event"] == "views" for record in records))

    def test_prune_rules(self):
        def user(*parts):
            return {"role": "user", "content": list(parts)}

        def view(name="screen", pin=None):
            return {"type": "input_image", "image_url": name, "detail": "auto", "view": name,
                    **({"pin": pin} if pin else {})}

        other = {"type": "input_image", "image_url": "file", "detail": "auto"}
        text = {"type": "input_text", "text": "t"}
        history = [user(text, dict(other)), {"role": "assistant", "content": "a"},
                   user(text, view(pin="p")), {"role": "assistant", "content": "a"},
                   user(text, view()), {"role": "assistant", "content": "a"}, user(text)]
        prune_views(history, 1, pins={"p"})
        self.assertEqual([len(images(message)) for message in history if message["role"] == "user"], [1, 1, 0, 0])
        prune_views(history, 1, pins=())
        self.assertEqual([len(images(message)) for message in history if message["role"] == "user"], [1, 0, 0, 0])
        # The legacy rule is untouched: the last `keep` messages that have an image.
        legacy = [user(text, dict(other)), user(text), user(text, dict(other)), user(text, dict(other))]
        prune_images(legacy, 2)
        self.assertEqual([len(images(message)) for message in legacy], [0, 0, 1, 1])
        self.assertEqual(len(view_parts([{"camera": "screen", "image_url": "u"}] * 12)), 16)

    def test_prompt_feature_follows_the_declaration(self):
        self.assertIn("look", features_for({"contract": "native"}, embodiment="desktop"))
        self.assertNotIn("look", features_for({"cameras": ["screen"]}, embodiment="desktop"))
        self.assertNotIn("look", features_for({}, embodiment="workspace"))  # nothing to look at
        core = ROOT / "src" / "harness" / "builtin" / "prompts" / "core"
        demand = assemble_prompt(core, [], features={"look"})
        standing = assemble_prompt(core, [], features=())
        self.assertIn("look(camera=None", demand)
        self.assertIn("A picture reaches you only when a program looks", demand)
        self.assertNotIn("look(", standing)
        self.assertIn("what went wrong if anything did and new\npictures.", standing)
        # The core's default names no kind; what a kind's package says of the agent on it
        # (kinds.toml: agent) declares no standing watch.
        import tomllib

        from harness.embodiments import KINDS

        default = tomllib.loads((ROOT / "src/harness/builtin/configs/default.toml").read_text(encoding="utf-8"))
        self.assertEqual(set(default) & set(KINDS), set())
        self.assertNotIn("prompt", default)
        for kind in KINDS.values():
            self.assertNotIn("cameras", kind.agent.get("runtime", {}))
            self.assertNotIn("keep_images", kind.agent.get("runtime", {}))
        # A kind brings its own prompt; the core's own kind reads the page every agent reads.
        self.assertTrue(KINDS["desktop"].prompt.replace(chr(92), "/").endswith("packages/computer/prompts/computer"))
        self.assertEqual(KINDS["none"].prompt, "")


if __name__ == "__main__":
    unittest.main()
