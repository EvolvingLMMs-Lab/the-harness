#!/usr/bin/env python3
"""Serve generic perception for programs that learn a game from its pictures: text,
open-vocabulary detection, depth, point or box segmentation, and small per-game models
trained on frames the agent labelled itself.

    CUDA_VISIBLE_DEVICES=0 python services/servers/serve_vision.py --weights /path/to/vision --port 8811

POST /ocr {"image": <data URL>, "region": [x0, y0, x1, y1] | null}
  -> {"lines": [{"text", "box": [x0, y0, x1, y1], "score"}]}           (RapidOCR, PP-OCR models)
POST /detect {"image", "labels": ["tree trunk", ...], "threshold": 0.3}
  -> {"detections": [{"label", "box", "score"}]}           (Grounding DINO tiny, or OWLv2)
POST /depth {"image", "stride": 2}
  -> {"depth": <base64 float16, row-major>, "shape": [h, w], "stride", "unit": "m"}
                                                           (Depth Anything V2 Small, metric outdoor)
POST /segment {"image", "points": [[x, y], ...], "labels": [1, ...]} or {"image", "box": [...]}
  -> {"masks": [{"score", "box", "mask": <PNG data URL, 0/255>}]}  best first (SAM 2.1 tiny)
POST /train {"name", "samples": [{"image", "masks": {label: <PNG data URL>}} or
             {"image", "boxes": [{"label", "box"}]}], "epochs", "seed"}
  -> {"job"}; GET /train/<job> -> {"state", "epoch", "loss", "error"}, and once done
  "model" (the ONNX file's SHA-256, its id), "labels" and "metrics" (held-out IoU);
  GET /model/<job> -> {"onnx": <base64>, "meta": {"labels", "input", "metrics"}}
POST /load {"onnx": <base64>, "meta"} -> {"model"}
POST /predict {"model", "image"}
  -> {"classes": <PNG data URL of label indices>, "labels", "regions": {index: {"pixels", "box"}}},
     or {"unknown": model} when it does not have that model (the client loads it, then asks again)

Trained models belong to the harness's library (the learner takes them as skill entries
with the weights attached); this server only caches them by their SHA-256 (--models).

Every model loads on its first request; all are open (Apache-2.0) and fit in about 2 GB
of GPU memory together. Weights are read from --weights (services/vision.toml fetches
them); nothing is downloaded at run time.
"""

import argparse
import base64
import hashlib
import io
import json
import threading
import time
import traceback
import sys
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# The package's library (harness_perception: OnnxModel), beside services/.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

MODELS = {
    "grounding-dino": "grounding-dino-tiny",
    "owlv2": "owlv2-base-patch16-ensemble",
    "depth": "Depth-Anything-V2-Metric-Outdoor-Small-hf",
    "sam2": "sam2.1-hiera-tiny",
    "backbone": "mobilenetv3_large_100.ra_in1k",
}
TRAIN_WIDTH = 640          # a trained model sees frames scaled to this width (height a multiple of 32)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--weights", required=True, help="the directory of the [[weights]] of services/vision.toml")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8811)
    parser.add_argument("--detector", choices=("grounding-dino", "owlv2"), default="grounding-dino")
    parser.add_argument("--models", default=None, help="where trained models are kept (default: WEIGHTS/../vision-trained)")
    args = parser.parse_args()
    server = make_server(args)
    print(json.dumps({"serving": "vision", "port": args.port, "detector": args.detector}), flush=True)
    server.serve_forever()


def make_server(args):
    import numpy as np
    import torch
    from PIL import Image

    device = "cuda" if torch.cuda.is_available() else "cpu"
    weights = Path(args.weights)
    trained = Path(args.models) if args.models else weights.parent / "vision-trained"
    loaded, lock, gpu = {}, threading.Lock(), threading.Lock()
    jobs = {}

    def model(name, load):
        with lock:
            if name not in loaded:
                began = time.perf_counter()
                loaded[name] = load()
                print(json.dumps({"loaded": name, "seconds": round(time.perf_counter() - began, 1)}), flush=True)
            return loaded[name]

    from harness.sdk import decode_data_url, image_data_url

    def decode(url):
        return Image.open(io.BytesIO(decode_data_url(url))).convert("RGB")

    def png(array):
        return image_data_url(array, "png")

    # -- text ----------------------------------------------------------------------
    def ocr(request):
        from rapidocr_onnxruntime import RapidOCR

        engine = model("ocr", RapidOCR)
        image = decode(request["image"])
        x0 = y0 = 0
        if request.get("region"):
            x0, y0, x1, y1 = (int(round(v)) for v in request["region"])
            image = image.crop((x0, y0, x1, y1))
        rgb = np.asarray(image)
        # Small HUD text reads better larger.
        scale = 2 if max(rgb.shape[:2]) < 400 else 1
        if scale > 1:
            rgb = np.asarray(image.resize((image.width * scale, image.height * scale), Image.BICUBIC))
        result, _ = engine(rgb[:, :, ::-1].copy())
        lines = []
        for points, text, score in result or []:
            xs, ys = [p[0] / scale + x0 for p in points], [p[1] / scale + y0 for p in points]
            lines.append({"text": text, "score": round(float(score), 3),
                          "box": [round(min(xs), 1), round(min(ys), 1), round(max(xs), 1), round(max(ys), 1)]})
        lines.sort(key=lambda line: (line["box"][1], line["box"][0]))
        return {"lines": lines}

    # -- open-vocabulary detection ---------------------------------------------------
    def load_detector():
        from transformers import AutoModelForZeroShotObjectDetection, AutoProcessor

        path = weights / MODELS[args.detector]
        return AutoProcessor.from_pretrained(path), \
            AutoModelForZeroShotObjectDetection.from_pretrained(path).to(device).eval()

    def detect(request):
        processor, net = model("detect", load_detector)
        image = decode(request["image"])
        labels = [str(label).strip() for label in request["labels"] if str(label).strip()]
        if not labels:
            raise ValueError("labels must name at least one thing")
        threshold = float(request.get("threshold", 0.3))
        detections = []
        with gpu, torch.inference_mode():
            if args.detector == "grounding-dino":
                text = ". ".join(label.lower() for label in labels) + "."
                inputs = processor(images=image, text=text, return_tensors="pt").to(device)
                outputs = net(**inputs)
                result = processor.post_process_grounded_object_detection(
                    outputs, inputs.input_ids, threshold=threshold, text_threshold=threshold,
                    target_sizes=[(image.height, image.width)])[0]
                names = result.get("text_labels", result.get("labels"))
                for box, score, phrase in zip(result["boxes"].tolist(), result["scores"].tolist(), names):
                    detections.append({"label": _closest(phrase, labels), "box": [round(v, 1) for v in box],
                                       "score": round(float(score), 3)})
            else:
                inputs = processor(text=[labels], images=image, return_tensors="pt").to(device)
                outputs = net(**inputs)
                # OWLv2 pads the image to a square: boxes are in the padded frame.
                side = max(image.width, image.height)
                result = processor.post_process_object_detection(outputs, threshold=threshold,
                                                                  target_sizes=[(side, side)])[0]
                for box, score, index in zip(result["boxes"].tolist(), result["scores"].tolist(),
                                             result["labels"].tolist()):
                    box = [min(max(v, 0.0), image.width if i % 2 == 0 else image.height) for i, v in enumerate(box)]
                    detections.append({"label": labels[index], "box": [round(v, 1) for v in box],
                                       "score": round(float(score), 3)})
        detections = _suppress(sorted(detections, key=lambda item: -item["score"]))
        return {"detections": detections}

    # -- depth -------------------------------------------------------------------------
    def load_depth():
        from transformers import AutoImageProcessor, AutoModelForDepthEstimation

        path = weights / MODELS["depth"]
        return AutoImageProcessor.from_pretrained(path), AutoModelForDepthEstimation.from_pretrained(path).to(device).eval()

    def depth(request):
        processor, net = model("depth", load_depth)
        image = decode(request["image"])
        stride = max(1, int(request.get("stride", 2)))
        size = (image.height // stride, image.width // stride)
        with gpu, torch.inference_mode():
            inputs = processor(images=image, return_tensors="pt").to(device)
            predicted = net(**inputs).predicted_depth
            out = torch.nn.functional.interpolate(predicted[:, None], size=size, mode="bilinear",
                                                  align_corners=False)[0, 0]
        array = out.float().cpu().numpy().astype(np.float16)
        return {"depth": base64.b64encode(array.tobytes()).decode(), "shape": list(array.shape), "stride": stride,
                "unit": "m"}

    # -- point or box segmentation -------------------------------------------------------
    def load_sam():
        from transformers import Sam2Model, Sam2Processor

        path = weights / MODELS["sam2"]
        return Sam2Processor.from_pretrained(path), Sam2Model.from_pretrained(path).to(device).eval()

    def segment(request):
        processor, net = model("segment", load_sam)
        image = decode(request["image"])
        kwargs = {}
        if request.get("box") is not None:
            kwargs["input_boxes"] = [[[float(v) for v in request["box"]]]]
        if request.get("points"):
            points = [[float(x), float(y)] for x, y in request["points"]]
            labels = [int(v) for v in request.get("labels") or [1] * len(points)]
            if len(labels) != len(points):
                raise ValueError("one label per point")
            kwargs["input_points"] = [[points]]
            kwargs["input_labels"] = [[labels]]
        if not kwargs:
            raise ValueError("give points or a box")
        with gpu, torch.inference_mode():
            inputs = processor(images=image, return_tensors="pt", **kwargs).to(device)
            outputs = net(**inputs, multimask_output=request.get("box") is None)
            masks = processor.post_process_masks(outputs.pred_masks.cpu(), inputs["original_sizes"])[0][0]
            scores = outputs.iou_scores[0, 0].float().cpu().numpy()
        found = []
        for mask, score in zip(masks.numpy(), scores):
            rows, cols = np.nonzero(mask)
            if not len(rows):
                continue
            found.append({"score": round(float(score), 3), "mask": png(mask.astype(np.uint8) * 255),
                          "box": [float(cols.min()), float(rows.min()), float(cols.max()), float(rows.max())]})
        found.sort(key=lambda item: -item["score"])
        return {"masks": found}

    # -- small per-game models -------------------------------------------------------------
    def train(request):
        samples = request.get("samples") or []
        if len(samples) < 4:
            raise ValueError("train needs at least 4 labelled samples")
        job = uuid.uuid4().hex[:12]
        jobs[job] = {"state": "running", "epoch": 0, "loss": None, "metrics": None, "error": None,
                     "name": str(request.get("name") or "model")}
        threading.Thread(target=_run_training, daemon=True,
                         args=(jobs[job], job, samples, int(request.get("epochs", 30)), int(request.get("seed", 0)))).start()
        return {"job": job}

    def _run_training(state, job, samples, epochs, seed):
        try:
            frames, targets, labels = [], [], ["background"]
            for sample in samples:
                image = decode(sample["image"])
                target = np.zeros((image.height, image.width), dtype=np.uint8)
                for label, url in (sample.get("masks") or {}).items():
                    if label not in labels:
                        labels.append(label)
                    mask = np.asarray(Image.open(io.BytesIO(decode_data_url(url))).convert("L")) > 127
                    target[mask] = labels.index(label)
                for item in sample.get("boxes") or []:
                    if item["label"] not in labels:
                        labels.append(item["label"])
                    x0, y0, x1, y1 = (int(round(v)) for v in item["box"])
                    target[max(y0, 0):y1, max(x0, 0):x1] = labels.index(item["label"])
                frames.append(image)
                targets.append(target)
            if len(labels) > 255:
                raise ValueError("at most 254 labels")
            onnx, metrics, shape = fit(frames, targets, labels, epochs, seed, state)
            sha = cache(onnx, {"labels": labels, "input": shape, "metrics": metrics})
            state.update(state="done", model=sha, metrics=metrics, labels=labels, input=shape)
        except Exception as error:
            state.update(state="failed", error=f"{type(error).__name__}: {error}")
            traceback.print_exc()

    def fit(frames, targets, labels, epochs, seed, state):
        import timm

        rng = np.random.default_rng(seed)
        height = int(round(frames[0].height * TRAIN_WIDTH / frames[0].width / 32)) * 32
        shape = [height, TRAIN_WIDTH]
        images = np.stack([np.asarray(f.resize((TRAIN_WIDTH, height), Image.BILINEAR)) for f in frames])
        masks = np.stack([np.asarray(Image.fromarray(t).resize((TRAIN_WIDTH, height), Image.NEAREST)) for t in targets])
        order = rng.permutation(len(images))
        held = order[:max(1, len(images) // 7)]
        used = order[len(held):]
        backbone = timm.create_model("mobilenetv3_large_100", features_only=True, out_indices=(1, 2, 3, 4),
                                     pretrained=True, pretrained_cfg_overlay={
                                         "file": str(weights / MODELS["backbone"] / "model.safetensors")})
        segmenter, exported = _modules()
        net = segmenter(backbone, len(labels)).to(device)
        optimiser = torch.optim.AdamW(net.parameters(), lr=1e-3, weight_decay=1e-4)
        steps = max(1, epochs * max(1, len(used) // 8))
        schedule = torch.optim.lr_scheduler.OneCycleLR(optimiser, max_lr=1e-3, total_steps=steps)
        mean = torch.tensor([0.485, 0.456, 0.406], device=device).view(1, 3, 1, 1) * 255
        std = torch.tensor([0.229, 0.224, 0.225], device=device).view(1, 3, 1, 1) * 255
        counts = np.bincount(masks[used].ravel(), minlength=len(labels)).astype(np.float64)
        weight = torch.tensor(np.clip((counts.sum() / np.maximum(counts, 1) / len(labels)) ** 0.5, 0.2, 10),
                              dtype=torch.float32, device=device)
        step = 0
        net.train()
        for epoch in range(epochs):
            losses = []
            for start in range(0, len(used), 8):
                batch = used[rng.permutation(len(used))][:8] if len(used) > 8 else used
                x = torch.from_numpy(images[batch]).to(device).permute(0, 3, 1, 2).float()
                y = torch.from_numpy(masks[batch]).to(device).long()
                if rng.random() < 0.5:
                    x, y = x.flip(-1), y.flip(-1)
                x = x * float(rng.uniform(0.7, 1.3))
                with gpu:
                    logits = net((x - mean) / std)
                    loss = torch.nn.functional.cross_entropy(logits, y, weight=weight)
                    optimiser.zero_grad()
                    loss.backward()
                    optimiser.step()
                if step < steps:
                    schedule.step()
                step += 1
                losses.append(float(loss))
            state.update(epoch=epoch + 1, loss=round(float(np.mean(losses)), 4))
        net.eval()
        export = exported(net, mean, std).eval()
        with gpu, torch.inference_mode():
            x = torch.from_numpy(images[held]).to(device)
            guess = torch.cat([export(x[i:i + 1])[0] for i in range(len(x))]).cpu().numpy()
        truth = masks[held]
        metrics = {"held_out": int(len(held)), "pixel_accuracy": round(float((guess == truth).mean()), 4),
                   "iou": {}}
        for index, label in enumerate(labels):
            union = ((guess == index) | (truth == index)).sum()
            if union and index:
                metrics["iou"][label] = round(float(((guess == index) & (truth == index)).sum() / union), 4)
        buffer = io.BytesIO()
        export = export.cpu()
        torch.onnx.export(export, torch.zeros(1, height, TRAIN_WIDTH, 3, dtype=torch.uint8), buffer,
                          input_names=["image"], output_names=["classes", "probability"], opset_version=17,
                          dynamic_axes={"image": {0: "batch"}})
        export.to(device)
        return buffer.getvalue(), metrics, shape

    def train_status(job):
        if job not in jobs:
            raise KeyError(f"no training job {job}")
        return {key: value for key, value in jobs[job].items()}

    def cache(onnx, meta):
        sha = hashlib.sha256(onnx).hexdigest()
        trained.mkdir(parents=True, exist_ok=True)
        (trained / f"{sha}.onnx").write_bytes(onnx)
        (trained / f"{sha}.json").write_text(json.dumps(meta))
        return sha

    def trained_model(job):
        state = train_status(job)
        if state["state"] != "done":
            raise ValueError(f"job {job} is {state['state']}")
        sha = state["model"]
        return {"onnx": base64.b64encode((trained / f"{sha}.onnx").read_bytes()).decode(),
                "meta": json.loads((trained / f"{sha}.json").read_text())}

    def load_model(request):
        meta = request.get("meta") or {}
        if not isinstance(meta.get("labels"), list):
            raise ValueError("meta needs the model's labels")
        return {"model": cache(base64.b64decode(request["onnx"]), meta)}

    sessions = {}

    def predict(request):
        from harness_perception.onnx import OnnxModel

        sha = str(request["model"])
        path = trained / f"{sha}.onnx"
        if not sha.isalnum():
            raise ValueError(f"not a model id: {sha}")
        if not path.exists():
            return {"unknown": sha}
        with lock:
            if sha not in sessions:
                sessions[sha] = (OnnxModel(path, devices=["CPUExecutionProvider"]),
                                 json.loads(path.with_suffix(".json").read_text())["labels"])
        model, labels = sessions[sha]
        height, width = model.inputs["image"][1:3]
        image = decode(request["image"])
        x = np.asarray(image.resize((width, height), Image.BILINEAR))[None]
        classes, _ = model.run(x)
        classes = np.asarray(Image.fromarray(classes[0].astype(np.uint8)).resize(image.size, Image.NEAREST))
        regions = {}
        for index in np.unique(classes):
            rows, cols = np.nonzero(classes == index)
            regions[int(index)] = {"pixels": int(len(rows)),
                                   "box": [int(cols.min()), int(rows.min()), int(cols.max()), int(rows.max())]}
        return {"classes": png(classes), "labels": labels, "regions": regions}

    posts = {"/ocr": ocr, "/detect": detect, "/depth": depth, "/segment": segment, "/train": train,
             "/load": load_model, "/predict": predict}
    gets = {"/train/": train_status, "/model/": trained_model}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *items):
            pass

        def _send(self, status, body):
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path.rstrip("/") == "/health":
                self._send(200, {"ok": True, "loaded": sorted(loaded)})
                return
            for prefix, route in gets.items():
                if self.path.startswith(prefix):
                    try:
                        self._send(200, route(self.path[len(prefix):].strip("/")))
                    except Exception as error:
                        self._send(400, {"error": f"{type(error).__name__}: {error}"})
                    return
            self._send(404, {"error": "not found"})

        def do_POST(self):
            route = posts.get(self.path.rstrip("/"))
            if route is None:
                self._send(404, {"error": "not found"})
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                started = time.perf_counter()
                body = route(json.loads(self.rfile.read(size)))
                print(json.dumps({"route": self.path, "seconds": round(time.perf_counter() - started, 3)}), flush=True)
                self._send(200, body)
            except Exception as error:
                self._send(400, {"error": f"{type(error).__name__}: {error}"})

    from harness.sdk import OwnPort

    class Server(OwnPort, ThreadingHTTPServer):
        pass

    return Server((args.host, args.port), Handler)


def _closest(phrase, labels):
    """The requested label a detector's phrase belongs to: the same text, else the label
    sharing the most words with it."""
    phrase = str(phrase).lower().strip()
    for label in labels:
        if label.lower() == phrase:
            return label
    words = set(phrase.split())
    return max(labels, key=lambda label: (len(words & set(label.lower().split())), -abs(len(label) - len(phrase))))


def _suppress(detections, overlap=0.7):
    """Drop a detection of a label whose box mostly covers a better one of that label."""
    kept = []
    for item in detections:
        if all(other["label"] != item["label"] or _iou(other["box"], item["box"]) < overlap for other in kept):
            kept.append(item)
    return kept


def _iou(a, b):
    x0, y0, x1, y1 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, x1 - x0) * max(0.0, y1 - y0)
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def _modules():
    """The small segmentation network a per-game model is (a MobileNetV3 backbone and a
    light FPN head), defined only once torch is imported."""
    import torch
    from torch import nn

    class Segmenter(nn.Module):
        def __init__(self, backbone, classes, width=64):
            super().__init__()
            self.backbone = backbone
            self.lateral = nn.ModuleList(nn.Conv2d(c, width, 1) for c in backbone.feature_info.channels())
            self.head = nn.Sequential(nn.Conv2d(width, width, 3, padding=1), nn.BatchNorm2d(width), nn.ReLU(),
                                      nn.Conv2d(width, classes, 1))

        def forward(self, x):
            features = self.backbone(x)
            out = self.lateral[-1](features[-1])
            for lateral, feature in zip(reversed(self.lateral[:-1]), reversed(features[:-1])):
                out = nn.functional.interpolate(out, size=feature.shape[-2:], mode="bilinear",
                                                align_corners=False) + lateral(feature)
            return nn.functional.interpolate(self.head(out), size=x.shape[-2:], mode="bilinear", align_corners=False)

    class Exported(nn.Module):
        """uint8 NHWC frames in; label indices (uint8) and their probability out."""

        def __init__(self, net, mean, std):
            super().__init__()
            self.net = net
            self.register_buffer("mean", mean.detach().clone())
            self.register_buffer("std", std.detach().clone())

        def forward(self, image):
            x = (image.permute(0, 3, 1, 2).float() - self.mean) / self.std
            probability, classes = torch.softmax(self.net(x), 1).max(1)
            return classes.to(torch.uint8), probability

    return Segmenter, Exported


if __name__ == "__main__":
    main()
