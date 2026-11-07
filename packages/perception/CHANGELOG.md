# Changelog

## 0.5.3

- For the harness 0.66.1: the segmenter and vision clients send their requests with the core's `post_json` and `open_url`.

## 0.5.2

- For the harness 0.65: the sam3 and vision servers, the clients and the vision skill decode and encode with the core's `decode_data_url` and `image_data_url`.

## 0.5.1

- For the harness 0.65: `image_data_url` is the core's; the clients add up usage with the core's `USAGE` and `add_usage` (`cost_usd`).

## 0.5.0

- For the harness 0.64: `harness_perception.frames.diff(a, b)`: the one frame difference (changed, magnitude, box, regions, shift, explained, grid, the mask when asked). `vision.diff` returns it: `explained` replaces `shift_score`.
- `harness_perception.onnx.OnnxModel`: an ONNX model on the best device (DirectML, CUDA, else the CPU); the vision service's trained models load through it.

## 0.4.0

- For the harness 0.63: VisionModel (the vlm, pointer and verifier roles' client), Molmo2's points and JPEG data URLs are the package's (harness_perception/clients.py); its host module names the class (vision_model), which the core's episode builds in the kernel.

## 0.3.0

- For the harness 0.59: The segmenter's and the vision service's clients are the package's (harness_perception/clients.py); each service's manifest names its client.

## 0.2.0

- For the harness 0.58: Camera geometry is the package's library (harness_perception); segmentation takes any observation with images.

## 0.1.0

- First release as a package of its own (moved out of the harness core).
