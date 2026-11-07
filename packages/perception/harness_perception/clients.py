"""The clients of the perception services (their manifests name them: [client] class):
the segmenter (SAM 3: masks from text or points) and the vision service (OCR, detection,
depth, masks), and Mask, the segmenter's result; and VisionModel, the client of the model
roles that answer about images (vlm, pointer, verifier: the core's episode builds them
from the class the package's host module names, vision_model), with Molmo2's points and
JPEG data URLs."""

import base64
import json
import re

import numpy as np

from harness.sdk import USAGE, ChatModel, add_usage, control, decode_data_url, image_data_url, json_list, open_url, post_json, span


def _url(image):
    return image if isinstance(image, str) else image_data_url(image)


class Mask:
    """One segmented instance: boolean HxW array, box [x0, y0, x1, y1], score."""

    def __init__(self, array, box, score):
        import numpy as np

        self.array = np.asarray(array, dtype=bool)
        self.box = [float(v) for v in box]
        self.score = float(score)

    @property
    def area(self):
        return int(self.array.sum())

    @property
    def centroid(self):
        import numpy as np

        rows, cols = np.nonzero(self.array)
        return (float(cols.mean()), float(rows.mean())) if len(rows) else None

    def pixels(self, step=1):
        """(u, v) pixel coordinates inside the mask, every `step`-th."""
        import numpy as np

        rows, cols = np.nonzero(self.array)
        return np.stack([cols, rows], axis=1)[::max(1, int(step))].astype(float)

    def __repr__(self):
        return f"Mask(score={self.score:.2f}, area={self.area}, box={[round(v) for v in self.box]})"

def decode_png(url):
    """A PNG data URL as a 2-D uint8 array (Pillow, which every environment has)."""
    import io

    from PIL import Image

    return np.asarray(Image.open(io.BytesIO(decode_data_url(url))).convert("L"))

class Segmenter:
    """Client of services/servers/serve_sam3.py."""

    def __init__(self, url, timeout=120.0, on_demand=None):
        self.url = url.rstrip("/") + "/segment"
        self.timeout = timeout
        # A segmenter placed on demand is started by the deploy's broker before a call.
        self.on_demand = on_demand

    def _post(self, route, body):
        from harness.sdk import ensure

        ensure({"on_demand": self.on_demand})
        with span("service", "segmenter", route=route):
            result = post_json(self.url.rsplit("/", 1)[0] + route, body, timeout=self.timeout)
        if "error" in result:
            raise RuntimeError(result["error"])
        return result

    @staticmethod
    def _masks(result):
        import cv2

        masks = []
        for item in result["instances"]:
            raw = np.frombuffer(decode_data_url(item["mask"]), dtype=np.uint8)
            masks.append(Mask(cv2.imdecode(raw, cv2.IMREAD_GRAYSCALE) > 127, item["box"], item["score"]))
        return masks

    def segment_point(self, image, points, labels=None):
        """Candidate masks of the object under the points (SAM 3 interactive predictor),
        best predicted IoU first."""
        points = [[float(u), float(v)] for u, v in points]
        labels = [1] * len(points) if labels is None else [int(v) for v in labels]
        return self._masks(self._post("/segment_point", {"image": image_data_url(image), "points": points,
                                                         "labels": labels}))

    def segment(self, image, prompt, threshold=None):
        """Instances best first. SAM 3 scores depend strongly on phrasing (on one
        image "bowl" scored 0.13 and "white bowl" 0.72 for the same three bowls), so
        by default instances are kept when they score at least half the best score
        (and at least 0.05); pass `threshold` for an absolute cut instead."""
        masks = self._masks(self._post("/segment", {"image": image_data_url(image), "prompt": str(prompt),
                                                    "threshold": 0.0}))
        if not masks:
            return []
        cut = float(threshold) if threshold is not None else max(0.05, 0.5 * masks[0].score)
        return [mask for mask in masks if mask.score >= cut]

class VisionService:
    """Client of services/servers/serve_vision.py: text, open-vocabulary detection,
    depth, point or box segmentation, and per-game models trained on labelled frames."""

    def __init__(self, url, timeout=120.0, on_demand=None):
        self.url = url.rstrip("/")
        self.timeout = timeout
        # A vision service placed on demand is started by the deploy's broker before a call.
        self.on_demand = on_demand

    def _call(self, route, body=None, timeout=None):
        from urllib.error import HTTPError

        from harness.sdk import ensure

        ensure({"on_demand": self.on_demand})
        try:
            with span("service", "vision", route=route.split("/")[1]),                     open_url(self.url + route, body, timeout=timeout or self.timeout) as response:
                result = json.load(response)
        except HTTPError as error:
            result = json.loads(error.read() or b"{}")
            if not result.get("error"):
                raise
        if result.get("error") and result.get("state") != "failed":
            raise RuntimeError(f"vision {route}: {result['error']}")
        return result

    def ocr(self, image, region=None):
        """Text lines [{"text", "box", "score"}] in the image or in `region`."""
        return self._call("/ocr", {"image": _url(image), "region": None if region is None else list(region)})["lines"]

    def detect(self, image, labels, threshold=0.3):
        """Boxes [{"label", "box", "score"}] of the things `labels` names, best first."""
        return self._call("/detect", {"image": _url(image), "labels": list(labels), "threshold": float(threshold)})[
            "detections"]

    def depth(self, image, stride=2):
        """Metric depth (metres) at 1/stride of the image's size, float32."""
        result = self._call("/depth", {"image": _url(image), "stride": int(stride)})
        return np.frombuffer(base64.b64decode(result["depth"]), dtype=np.float16).reshape(result["shape"]).astype(
            np.float32)

    def segment(self, image, points=None, labels=None, box=None):
        """Masks under `points` (labels 1 on the thing, 0 off it) or in `box`, best first."""
        body = {"image": _url(image)}
        if points is not None:
            body["points"] = [[float(x), float(y)] for x, y in points]
            body["labels"] = [1] * len(body["points"]) if labels is None else [int(v) for v in labels]
        if box is not None:
            body["box"] = [float(v) for v in box]
        return [Mask(decode_png(item["mask"]) > 127, item["box"], item["score"])
                for item in self._call("/segment", body)["masks"]]

    def train(self, name, samples, epochs=30, seed=0):
        """Start training a per-game model; its job id."""
        return self._call("/train", {"name": name, "samples": samples, "epochs": int(epochs), "seed": int(seed)},
                          timeout=max(self.timeout, 600.0))["job"]

    def job(self, job):
        """A training job's state: {"state", "epoch", "loss", "error"}, and its model once done."""
        return self._call(f"/train/{job}")

    def model(self, job):
        """A finished job's model: (ONNX bytes, {"labels", "input", "metrics"})."""
        result = self._call(f"/model/{job}", timeout=max(self.timeout, 600.0))
        return base64.b64decode(result["onnx"]), result["meta"]

    def predict(self, model, image, fetch=None):
        """A trained model's (its id) label index of every pixel (HxW uint8), its labels
        and its regions {index: {"pixels", "box"}}. When the service does not have the
        model, fetch(model) -> (ONNX bytes, meta) gives it (from the library)."""
        body = {"model": str(model), "image": _url(image)}
        result = self._call("/predict", body)
        if "unknown" in result:
            if fetch is None:
                raise RuntimeError(f"the vision service does not have model {model}")
            onnx, meta = fetch(str(model))
            self._call("/load", {"onnx": base64.b64encode(onnx).decode(), "meta": meta},
                       timeout=max(self.timeout, 600.0))
            result = self._call("/predict", body)
        regions = {int(index): region for index, region in result["regions"].items()}
        return decode_png(result["classes"]), list(result["labels"]), regions


_POINT_SYSTEM = (
    "You locate things in images. Reply only with JSON: a list of objects "
    '{"point_2d": [x, y], "label": "..."} where x and y are integers from 0 to 1000 '
    "relative to the image width and height. Return an empty list if the thing is not visible."
)


class VisionModel:
    """A vision-language model role (vlm, pointer or verifier) on a ChatModel, at
    temperature 0 with 1024 output tokens unless its config says otherwise. `usage` adds
    up its calls, tokens and cost; `point_format` (json or molmo) is how it points."""

    def __init__(self, config, role="vlm"):
        config = dict(config)
        # The role it plays (vlm, pointer, verifier), as the timeline names its calls.
        self.role = role
        # "json": Qwen-style {"point_2d": [x, y]} replies; "molmo": Molmo2's <points coords=...>.
        self.point_format = config.pop("point_format", "json")
        if self.point_format not in ("json", "molmo"):
            raise ValueError("point_format must be json or molmo")
        # Pointing needs full-resolution images; a local server may otherwise downscale them.
        extra = {"max_image_side": 0} if config.get("backend") == "openai_chat" else {}
        self.chat = None if control.host_thoughts else ChatModel(
            {"max_output_tokens": 1024, "temperature": 0.0, "extra_body": extra, **config})
        # Tokens and cost of every call, reported with the episode.
        self.usage = {"calls": 0, **USAGE}

    def ask(self, images, question, system="Answer briefly and precisely."):
        """The model's text answer to `question` about `images` (RGB arrays, sent as JPEG)
        under `system`; the call is added to `usage`."""
        return self.reply(images, question, system).text

    def reply(self, images, question, system="Answer briefly and precisely.", *, frame=None):
        """As ask(), the whole reply: .text, .usage (tokens, cost) and .seconds. An image may
        also be a data URL already (a worker's picture), sent as it is."""
        urls = [image if isinstance(image, str) else image_data_url(image) for image in images]
        if control.host_thoughts:
            return control.think(self.role, question, images=urls, system=system, frame=frame)
        from harness.sdk import think

        content = [*({"type": "input_image", "image_url": url, "detail": "auto"} for url in urls),
                   {"type": "input_text", "text": question}]
        reply = think(self.chat, system, [{"role": "user", "content": content}], role=self.role, trigger="request")
        self.usage["calls"] += 1
        add_usage(self.usage, reply.usage)
        return reply

    def point(self, image, prompt):
        """The pixel points (x, y) the model gives for `prompt` in `image`, read from its
        0-1000 coordinates (JSON point_2d, or Molmo2 points); [] when it gives none."""
        height, width = np.asarray(image).shape[:2]
        if self.point_format == "molmo":
            # Molmo2's own pointing prompt, without a system message.
            return molmo_points(self.ask([image], f"Point to the {prompt}.", system=""), width, height)
        text = self.ask([image], f"Point to: {prompt}", system=_POINT_SYSTEM)
        results = []
        for item in json_list(text):
            point = item.get("point_2d") or item.get("point") if isinstance(item, dict) else None
            if not (isinstance(point, (list, tuple)) and len(point) == 2):
                continue
            x, y = float(point[0]), float(point[1])
            results.append((x / 1000.0 * width, y / 1000.0 * height))
        return results


def molmo_points(text, width, height):
    """Pixels from a Molmo2 reply: <points coords="1 1 433 424 2 614 465">...</points>,
    i.e. the image number, then index x y per point with x and y scaled to 0-1000
    (Molmo 1's <point x="52.3" y="40.2"> in percent too)."""
    points = []
    for coords in re.finditer(r'coords="([^"]*)"', text or ""):
        for match in re.finditer(r"(\d+) (\d{3,4}) (\d{3,4})", coords.group(1)):
            points.append((float(match.group(2)) / 1000.0 * width, float(match.group(3)) / 1000.0 * height))
    for match in re.finditer(r'<point\b[^>]*?\bx="([\d.]+)"[^>]*?\by="([\d.]+)"', text or ""):
        points.append((float(match.group(1)) / 100.0 * width, float(match.group(2)) / 100.0 * height))
    return [(x, y) for x, y in points if 0 <= x <= width and 0 <= y <= height]

