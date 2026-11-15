# Changelog

## 0.5.4

- The core prompt is less than half as long. It keeps what every reply needs: how to reply, how to work, and one line for each call. The details of the tree of reflexes (every setting of a node) and of units (waits, what the model is told and in what order, units of its own, who has the environment) are in two pages that a program reads on demand, `guide("tree")` and `guide("units")`. A page that was read is given again after a summary of the conversation. `reflex_method()` still works and returns `guide("tree")`. The other sections are brought to the same standard. The request for a reflection after an episode, the same whatever the agent acts in, asks for a note, a memory entry or a skill and no longer for a reactive helper: the nodes of a tree are kept from the tree the agent set. The library section gives `setup` in the signature of `library.propose` and no longer names a `tree` call. The checklist section has no example task. The section on world memory, which no setting could switch on and whose calls do not exist, is removed. The core names no kind of environment any more. Its default configuration has no table for a computer or a game and no table of prompts: a kind's package says its prompt and the agent's settings on it in its `kinds.toml` (`prompt`, `agent`), and may declare what is particular to the kind (`unnamed_in_lock`, `library_experience`, `record_waits`, `memory_report`, `interfaces`). Where nothing names a kind, it is `none`, a conversation with no environment, not a robot. What breaks: a `skill.toml` must say `embodiments` (the kinds it runs on, or `["*"]`); an embodiment file and a worker's profile must name their `kind`; `harness.embodiments.profile()` is gone (it built one kind's worker profile and is that kind's package's). `verify(claim)` is a call of every kind. The rest of what the core held of one package is that package's now. The session host and the command line name no workspace kind: a provider says where its kinds stand among those offered (`order` in `describe`), what it preselects (`preselected`), and a package adds its own flags to `harness run` (its host module's `run_arguments` and `run_sets`; `--vm-image` is the computer package's). `environment_kinds()` lists what a conversation can take, so no prompt lists kinds. A package brings the third-party sources it uses (`third_party/sources.toml` in the package); the core's list is empty. A service of a protocol that is not the core's (`http`, `openai_chat`, `mcp`) names it and gives that protocol's own table, read as `ServiceSpec.options` (it was `ServiceSpec.xpolicylab`). The guard actions `OPEN_GRIPPER` and `BACK_OFF` and the prompt feature `measured_gripper` are no longer the core's: the package of the kind that has them names them. The pins `environment/constraints.txt` of the core, which were one benchmark's, are gone: the browser benchmark's environment no longer names them (it is built anew on its next use). A prompt pack needs `pack.toml`: the section list for packs without one, which named skills of packages, is removed. Direct mode's action vocabulary (`runtime.actions`) is called with `skills`, the enabled skills, in place of `allow_policy`.

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
