# perception

The perception package gives programs eyes: questions about images, instance masks, open-vocabulary pointing and 3D localization on a robot, scene watching, and generic vision (changes, text, boxes, depth, masks and small self-trained models) for any game or screen.

## Install

```bash
harness install perception
```

A run whose agent uses one of its skills installs it by itself the first time (`packages.auto_install`, see [Packages](https://harness.lmms-lab.com/docs/configure/packages/)).

Each model runs as a service in an environment of its own, built the first time a run calls it; its weights are downloaded then too. To do it ahead of time, name the services:

```bash
harness install sam3 vision      # environments, sources and weights
harness fetch molmo2             # weights only
```

Outside Python you need an NVIDIA GPU with a driver recent enough for CUDA 12.8 builds of PyTorch, for each service you run locally:

| Service | GPU memory |
|---|---|
| `sam3` | about 7 GB |
| `molmo2` | about 13 GB |
| `vision` | about 3 GB with every model loaded |

`query_vlm` and pointing through the `vlm` role need no GPU when that role is a hosted model.

## Use

### On a robot

Turn on a segmenter in the agent file; pointing and `query_vlm` use the model roles:

```toml
[services]
segmenter = "sam3"
```

Programs then see:

```python
obs = get_observation()
masks = segment_text(obs, "white bowl")                    # instance masks, best first, or []
pixels = point_to(obs, "red cup")                           # [(u, v), ...] in cam_head
cup = localize_3d(obs, "red cup")                           # {"position", "cameras", "residual_m", "single_view"}
answer = query_vlm(obs.images["cam_left_wrist"], "Is the gripper holding the cup?")
```

`segment_text` scores depend on phrasing: describe color and object ("white bowl") or use a plural. When it finds nothing, point first and segment the pixel with `segment_point`. `localize` intersects the pixel ray with a horizontal plane (the table top by default), so for tall objects pass the height of the pointed part, or use `localize_3d`, which triangulates across the head and wrist cameras.

`watch_scene` holds both arms still and records frames, for watching a demonstration; `clear_view` moves both arms out of the head camera's view; `press` presses a button with the closed fingertips.

### On a game or a screen

The `vision` skill knows nothing about the game or app in front of it. Name the skill and its service in the agent file:

```toml
[services]
vision = "vision"

[skills]
enable = ["vision"]
```

```python
a = get_observation(); hold("w", 0.5); b = get_observation()
vision.diff(a, b)                       # {changed, magnitude, box, regions, shift [dx, dy], explained, grid}
vision.ocr(b, region=None)              # [{text, box, score}]
vision.detect(b, ["tree trunk", "zombie"])   # [{label, box, score}]
vision.depth(b)                         # metres, at half the frame's size
vision.segment(b, (640, 360))           # masks under a pixel, or in a box
```

`diff` is how an agent learns its controls: press a key between two frames and look. A camera turn shows as a `shift`; a menu, an item count or a health bar shows as a `region`.

When plain words are not enough for something the agent needs often, it labels frames from practice and trains a small model:

```python
result = vision.train("trunks", [{"frame": f, "masks": {"trunk": m}} for f, m in labelled])
vision.predict("trunks", frame)["regions"]   # {"trunk": {"pixels", "box"}}
```

`train` hands the model to the learner as a skill entry, `trunks(frame=None)`, with a test and its weights attached. It goes through the same checks as any learned skill and into the same library. The service only caches models by their SHA-256; a later episode with the library but a fresh service loads the weights from the entry.

## What it provides

Skills:

- `vlm`: `query_vlm(images, question)`, questions about one or more images (needs a `vlm` role).
- `segmentation`: `segment_text`, `segment_point`, instance masks from a text prompt or a pixel (needs a segmenter).
- `pointing`: `point_to`, `localize`, `localize_3d`, open-vocabulary pointing and 3D localization (needs a `pointer` or a `vlm` role).
- `scene`: `watch_scene`, `clear_view`, `press` on a robot (needs pointing).
- `vision`: `vision.diff`, `ocr`, `detect`, `depth`, `segment`, `train`, `predict` on games and desktops (optional; needs the `vision` service).

Services:

- `sam3`: SAM 3 instance segmentation from text or point prompts (kind `segmenter`).
- `molmo2`: Molmo2-8B open-vocabulary pointing, 8 bit with the vision tower in bf16 (kind `pointer`).
- `vision`: generic perception: RapidOCR, Grounding DINO tiny, Depth Anything V2 Small (metric), SAM 2.1 tiny, and a MobileNetV3 backbone for `train`; all Apache-2.0, each loaded on its first request (kind `vision`).

Library (`harness_perception`, for other packages):

- `geometry`: camera rays, projections and pose matrices.
- `frames`: `diff(a, b)`, the one frame difference (what changed, where, and how far the picture moved). `vision.diff` returns it, and the game's and the robot's body probes read inputs off it.
- `onnx`: `OnnxModel(path)`, an ONNX model on the best device here (DirectML, CUDA, else the CPU).

The `eef`, `manipulation` and `reflexes` skills of the `robot` package call `segmentation` and `pointing` from this package.

## Configuration

Agent file:

| Key | Meaning |
|---|---|
| `[services] segmenter` | the segmenter service, e.g. `"sam3"`; `""` for none |
| `[services] vision` | the vision service for the `vision` skill |
| `[skills] enable` | optional skills, e.g. `["vision"]` |
| `roles` | model roles the agent uses, among `main`, `vlm`, `pointer`, `verifier` |

Model file (`configs/models/<name>.toml`):

```toml
[vlm]          # query_vlm, and pointing when there is no pointer role
service = "qwen3-vl-8b"

[pointer]      # open-vocabulary pointing
service = "molmo2"
```

Without a `[pointer]` table, the `vlm` role points; without either, `pointing` and `scene` drop, and without a `[vlm]` table `query_vlm` drops. A role can name a hosted model instead of a service (`model = "..."`). See [Models](https://harness.lmms-lab.com/docs/configure/models/).

Deploy file, to place a service yourself:

```toml
[services.vision]
gpu = "auto"
mode = "on_demand"
```

See [Services](https://harness.lmms-lab.com/docs/configure/services/) for `mode`, `swap` and `idle_seconds`.

`harness config` shows which of these skills are on and why the others dropped ("no segmenter service", "needs one of the services pointer, vlm").

## Limits and known issues

- A skill whose service or role is missing drops out of the run, and the prompt drops its text with it. On evaluation layouts the run refuses instead.
- `segment_text` matches names loosely: check a mask against the image before acting on it.
- On a robot, the arms can hide objects from the head camera; move an arm aside and observe again.
- `localize_3d` falls back to one camera's ray at 2 cm above the table when no two views agree (`single_view` is `True`).
- Generic vision tells an agent where to look and what changed. It does not give a reliable object map of a game that looks unlike photographs: open-vocabulary detection misnames stylized creatures and blocks. Train a model of the agent's own with `vision.train` for that.
- The `vision` skill runs on games and desktops only; the robot skills run on robots only.
