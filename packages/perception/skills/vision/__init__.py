"""Generic perception for a game (or any screen) learned from its pictures: the `vision`
object programs call. diff runs here (NumPy); the rest is the vision service
(services/servers/serve_vision.py), installed and started on first use."""

import json
import time



class _NumPy:
    """numpy, imported the first time vision uses it: the kernel of a browser or desktop
    task can run in an interpreter without it, and the session imports this module."""

    def __getattr__(self, name):
        import numpy

        return getattr(numpy, name)


np = _NumPy()


class VisionSkill:
    """The session side: the `vision` export."""

    def _vision_tools(self):
        if getattr(self, "_vision_tools_", None) is None:
            self._vision_tools_ = Vision(self)
        return self._vision_tools_


def exports(session):
    return {"vision": session._vision_tools()}


class Vision:
    """What a frame shows, without knowing the game. A frame is an RGB array (HxWx3
    uint8), a screenshot (its .image) or None for the screen now. Boxes are window
    pixels [x0, y0, x1, y1]."""

    def __init__(self, session):
        self._session = session
        self._models = {}       # name -> {"model", "labels", "metrics"} trained this episode

    # -- frames --------------------------------------------------------------------------
    def _frame(self, frame):
        if frame is None:
            frame = self._session.get_observation()
        if hasattr(frame, "image"):
            frame = frame.image
        elif hasattr(frame, "images"):
            frame = next(iter(frame.images.values()))
        array = np.asarray(frame)
        if array.ndim != 3 or array.shape[-1] != 3:
            raise ValueError("a frame is an HxWx3 RGB array, a screenshot, or None for the screen now")
        return np.ascontiguousarray(array[..., :3]).astype(np.uint8, copy=False)

    def _service(self):
        service = getattr(self._session, "vision_service", None)
        if service is None:
            raise RuntimeError("No vision service is configured for this harness (services.vision)")
        return service

    # -- here ----------------------------------------------------------------------------
    def diff(self, a, b, threshold=24, min_pixels=64):
        """What changed from frame `a` to frame `b` (harness_perception/frames.py): {"changed":
        share of pixels that changed, "magnitude": mean change 0-1, "box" around all of it,
        "regions": [{"box", "pixels", "mean"}] the changed areas (largest first, at most 20),
        "shift": [dx, dy] how far the whole picture moved (pixels; a turn of the camera),
        "explained": the share of the change the shift accounts for, "grid": the mean change
        in a 4 x 4 grid}. A key that moves the camera shows as a shift; one that opens a menu
        as a region."""
        from harness_perception import frames

        return frames.diff(self._frame(a), self._frame(b), threshold, min_pixels)

    # -- the service -----------------------------------------------------------------------
    def ocr(self, frame=None, region=None):
        """Text in the frame (or in `region`): [{"text", "box", "score"}], top to bottom."""
        return self._service().ocr(self._frame(frame), region)

    def detect(self, frame=None, labels=(), threshold=0.3):
        """Boxes of the things `labels` names ("tree trunk", "zombie", "health bar"):
        [{"label", "box", "score"}], best first. Plain words work best."""
        if isinstance(labels, str):
            labels = [labels]
        return self._service().detect(self._frame(frame), labels, threshold)

    def depth(self, frame=None, stride=2):
        """Metric depth in metres (an estimate from the picture alone) at 1/stride of the
        frame's size: a float32 array; depth[y // stride, x // stride] is pixel x, y's."""
        return self._service().depth(self._frame(frame), stride)

    def segment(self, frame=None, point_or_box=None, background=()):
        """Masks of the thing under a pixel (x, y), several pixels [(x, y), ...] or a box
        [x0, y0, x1, y1], best first: each has .array (HxW bool), .box, .score, .area and
        .centroid. `background` pixels are not on it."""
        if point_or_box is None:
            raise ValueError("segment needs a point (x, y), points or a box")
        frame = self._frame(frame)
        values = list(point_or_box)
        if len(values) == 4 and not hasattr(values[0], "__len__"):
            return self._service().segment(frame, box=values)
        points = [values] if len(values) == 2 and not hasattr(values[0], "__len__") else values
        points = [tuple(p) for p in points] + [tuple(p) for p in background]
        labels = [1] * (len(points) - len(background)) + [0] * len(background)
        return self._service().segment(frame, points=points, labels=labels)

    def train(self, name, samples, epochs=30, timeout=1800):
        """Train a small model of this game's pictures from frames you labelled: samples
        are {"frame", "masks": {label: HxW bool array}} (from segment or detect) or
        {"frame", "boxes": [{"label", "box"}]}; at least 4, better 50 or more. The model
        goes to the library as a skill `name(frame=None)` -> {label: {"pixels", "box"}}
        with its weights and metadata attached. The proposal awaits independent evaluation.
        Returns {"model": its id, "labels", "metrics": IoU on the training job's split,
        "proposed": the learner's answer (None without a learner)}. You can use
        predict(name, frame) to inspect the training result in this episode."""
        service = self._service()
        encoded = [_sample(self, sample) for sample in samples]
        job = service.train(name, encoded, epochs=epochs)
        began = time.monotonic()
        while True:
            state = service.job(job)
            if state["state"] == "done":
                break
            if state["state"] == "failed":
                raise RuntimeError(f"training {name} failed: {state['error']}")
            if time.monotonic() - began > timeout:
                raise TimeoutError(f"training {name}: still at epoch {state['epoch']} after {timeout} s")
            time.sleep(2.0)
        onnx, meta = service.model(job)
        model = {"model": state["model"], "labels": list(meta["labels"]), "metrics": meta["metrics"]}
        self._models[name] = model
        code, test = library_skill(name, model, len(encoded))
        attachments = {"model.onnx": onnx, "model.json": json.dumps(meta)}
        return {**model, "proposed": propose(self._session, name, code, test, attachments)}

    def predict(self, model, frame=None, labels=None):
        """A trained model's reading of a frame: {"classes": HxW uint8 label indices,
        "labels", "regions": {label: {"pixels", "box"}}}. `model` is a name trained this
        episode or a model's id (a library skill names its own)."""
        known = self._models.get(model)
        sha = known["model"] if known else model
        fetch = lambda wanted: (attachment(self._session, wanted), {"labels": list(labels or ())})
        classes, named_labels, regions = self._service().predict(sha, self._frame(frame), fetch=fetch)
        named = {(named_labels[i] if i < len(named_labels) else i): region for i, region in regions.items() if i}
        return {"classes": classes, "labels": named_labels, "regions": named}


# The learner (the learning skill's `library` in the program namespace): how a trained
# model enters the library and how its weights come back.
def _learner(session):
    return (getattr(session, "namespace", {}) or {}).get("library")


def propose(session, name, code, test, attachments):
    """Submit the trained bytes and inference code together as a library proposal."""
    learner = _learner(session)
    if learner is None or not hasattr(learner, "propose"):
        return None
    return learner.propose("skill", name, code, test=test, summary=f"vision model {name}", attachments=attachments)


def attachment(session, model):
    """The weights of model `model` (the SHA-256 of its model.onnx) from the library."""
    learner = _learner(session)
    if learner is None or not hasattr(learner, "attachment"):
        raise RuntimeError(f"the vision service does not have model {model}, and no library can give it")
    return learner.attachment(model)


def library_skill(name, model, samples):
    """The code and test of a skill wrapping a trained model, for the library."""
    labels = [label for label in model["labels"] if label != "background"]
    function = _identifier(name)
    iou = ", ".join(f"{label} {value:.2f}" for label, value in (model["metrics"].get("iou") or {}).items())
    code = f'''"""{name}: where {", ".join(labels)} are in a frame. A model vision.train trained on
{samples} frames labelled in practice (training-job split IoU: {iou or "none measured"}); its weights are
this entry's model.onnx."""


def {function}(frame=None):
    """{{label: {{"pixels", "box"}}}} for the labels seen in the frame (the screen now by default)."""
    return vision.predict("{model["model"]}", frame, labels={model["labels"]!r})["regions"]
'''
    test = f'''def test_{function}():
    found = {function}()
    assert isinstance(found, dict)
    assert set(found) <= {set(labels)!r}
'''
    return code, test


def _identifier(name):
    return "".join(c if c.isalnum() else "_" for c in str(name)).strip("_") or "model"


def _sample(vision, sample):
    """A training sample as the service takes it: the frame and masks as PNG/JPEG data URLs."""
    from harness.sdk import image_data_url

    out = {"image": image_data_url(vision._frame(sample.get("frame", sample.get("image"))))}
    if sample.get("masks"):
        out["masks"] = {str(label): _png(np.asarray(getattr(mask, "array", mask), dtype=bool))
                        for label, mask in sample["masks"].items()}
    if sample.get("boxes"):
        out["boxes"] = [{"label": str(item["label"]), "box": [float(v) for v in item["box"]]} for item in sample["boxes"]]
    if "masks" not in out and "boxes" not in out:
        raise ValueError("a sample needs masks or boxes")
    return out


def _png(mask):
    from harness.sdk import image_data_url

    return image_data_url(mask.astype(np.uint8) * 255, "png")
