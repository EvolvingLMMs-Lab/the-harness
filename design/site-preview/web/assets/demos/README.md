# Recorded homepage demos

These small review clips replace the synthetic placeholders. They are the current 360p candidates, not newly recorded evaluations or upscaled 720p masters. Original recordings, raw camera frames, traces and failed attempts stay in the existing server evidence archive. No raw archives or server identities belong in this directory.

`../../demos.js` contains localized descriptions and trace-derived intervals on each edited video clock. The Multimodal clips carry no timeline: computer use (M1), coding (M2), robot (M3) and game (M4) are four-task montages of success moments, with their provenance below. Source moments: robot selected successful dual-arm actions from four RoboDojo episodes at 2× (center-cropped 16:9 head-camera footage) Their posters are frames of the same moments. Events are clipped to the selected excerpts; point events remain ticks rather than invented durations. A3 is a 1.5× RoboDojo organize-table long-horizon success (catalog id organize-table); old bowl-stacking timeline lanes were dropped. Legacy note — previously A3 divided focus PTS and event times by 1.5: 16x becomes 24x wall-clock speed, 30.6s becomes 20.4s. No interpolated frames. M3 uses recorded camera-frame occupancy at 25Hz simulation time, not wall-clock elapsed time.

Seven clips are usable candidates. Provenance and limitations stay in this record, not in added captions on the product page. M3 is a 2× four-task RoboDojo montage of harder success tails (cover-blocks / organize-table / sort-dolls / make-kong) with 0.22s dissolves and a 0.85s end fade-out; final duration 11.360s.  A1 uses an existing hand-authored reactive rule and a staged encounter; two later deaths remain part of its full run. M4 is a four-task Minecraft montage, 3 s each in first person, hard-cut, 640×360: chopping an oak trunk, placing planks, shooting a skeleton with a bow and a sword kill on a zombie. The agent (grok-4.7, low effort) acted through Minecraft tools served over MCP, which drive the real 1.16.1 client (view, keys, buttons) and read positions over RCON from a local offline server; scenes were staged by RCON before each run (a flattened patch inside an invisible barrier ring, the tool or weapon given, a planted tree, a helmeted zombie or a slowed skeleton, hidden resistance on the player). Source runs: tree 51.9–54.9 s (10 logs, model finished, 6 calls), build 399.0–402.0 s (planks placed; the hut was not finished), archery 39.6–42.6 s (one skeleton killed with the bow), combat 60.8–63.8 s (three zombies killed, model finished, 5 calls). Six earlier attempts failed and stay on the server: the zombie burned or wandered off, shield refusals of mistaken user input left the player defenceless, `click()` on screen coordinates swung the view away, and knockback pushed the player out of the patch. Its coming-soon label remains.

| Clip | Duration (s) | SHA256 |
| --- | ---: | --- |
| multimodal-computer | 11.680 | `f63785000e14163d8d5510c731a0286d72808b350862158f7b838af534c33a35` |
| multimodal-coding | 11.400 | `dcabdb1ee84bf07245e6986560837994886199c4fe138d79f25a4a0529fd80ac` |
| multimodal-robot | 11.360 | `33ec9ac81c22168d9e003a904818f4a10d0e1b5fe29cdd539544c2b6dd9d1142` |
| multimodal-game | 12.000 | `9e4f6a171db57d747fcf827489b1a2628e88632457fbae14c1a0e0724d339f90` |
| run-continuously | 9.000 | `7f87c384b79921344290c29b6da417c990adb6d61a215909a4d21fd3faded427` |
| one-call | 10.520 | `180efbf8457336c666c39e20903ef265d2c15754362836f652781df6d79a9c03` |
| think-while-acting | 9.160 | `12e943a0891b8ebc9af389857d1749148e983d22f0570253a09e22cbc31dabd0` |
| learn-while-working | 10.000 | `e5c7917eeb5ec5ef205d608b222c6663a45bf0c00ae89e14b93e86d90835d6a3` |

One-call (A2) was re-recorded on 2026-11-10 and learn-while-working (A4) was replaced on 2026-11-12; their provenance is below.

## M1 computer-use montage provenance

Recorded 2026-11-10 with the Harness 0.81.1 release installed from PyPI into a clean environment. Each take is one `harness run --workspace desktop --physical allow` with the task as typed below. All model calls used `deepseek/deepseek-v4.1-flash`. The desktop is a dressed 1280×720 virtual Linux desktop (Openbox, Google Chrome, LibreOffice Calc 26.8), captured continuously at 30 fps with the pointer drawn.

Every excerpt ends on the task's result, and each result was checked on the take's final frame. Excerpts are cut on the original clock (end-exclusive) and joined with 0.22 s dissolves and a 0.85 s fade-out at the end. The clip is encoded at 640×360, 25 fps, libx264 CRF 18, faststart; the 1280×720 master is kept with the raw takes.

| Task as typed | Source interval (s) | Speed | Visible action | Take |
| --- | --- | --- | --- | --- |
| In the Excalidraw whiteboard open in Chrome, draw a flowchart of how a pull request gets merged: four boxes labelled "Write code", "Open PR", "Review" and "Merge", in one row from left to right, each joined to the next by an arrow. | 89.6–97.4 | 2.5× | The arrows are drawn and the flowchart is complete | 104 s |
| In LibreOffice Calc, enter this table starting at cell A1: a header row "Month" and "Sales", then Jan 120, Feb 135, Mar 160, Apr 155, May 190, Jun 210. Then insert a column chart of sales by month beside the table. | 239.0–242.0 | 1× | The chart dialog is confirmed and the column chart appears | 552 s |
| In Bing Maps, get driving directions from the Golden Gate Bridge to Fisherman's Wharf in San Francisco. | 69.4–76.0 | 2.2× | The route card and the route line appear | 109 s |
| In the Desmos graphing calculator open in Chrome, plot y = sin(x), then y = cos(x), then their sum y = sin(x) + cos(x). | 14.4–23.0 | 2.7× | cos(x) and then the sum are plotted | 29 s |

Limitations:
- **Excalidraw:** the run deleted its first boxes and redrew them; that part is outside the excerpt.
- **Calc:** the chart dialog stays on screen for about 2 s before the model confirms it.
- **Bing Maps:** opened as an app window. Its attribution line carries a map approval number.
- **Changes from the plan:** OpenStreetMap was not reachable from the recording machine, so the map task uses Bing Maps. A file-manager task was dropped because its location bar showed absolute paths of the machine.

## M2 coding montage provenance

Recorded 2026-11-10 with the same Harness 0.81.1 release and model. Each take starts the Harness terminal chat (`harness --folder .`) in a project folder, in a terminal on the same desktop (Ubuntu Mono 17). The task is typed into the chat:

> The test suite in this project fails. Find the cause and fix it, run the tests again, and end with the diff of your fix in a diff code block and the test summary.

Each excerpt is 3.0 s at 1×, from 1.2 s before the model's final answer appears to 1.8 s after. It is cut and joined like M1. After each take, the project's own test command was run again outside the chat to confirm the fix.

| Project (tag) | Failure the task starts from | Source interval (s) | Fix in the excerpt | Tests after | Cost |
| --- | --- | --- | --- | --- | --- |
| boltons (25.0.0) | Upstream bug: `IndexedSet.update` with several iterables chains the iterables themselves; a regression test was added | 421.8–424.8 | `chain(others)` → `chain.from_iterable(others)` | 424 passed | USD 0.011 |
| ufo (v1.6.1) | Seeded: `joinURL` drops the separator | 258.2–261.2 | `withTrailingSlash(url)` restored | 477 passed | USD 0.028 |
| more-itertools (v10.7.0) | Seeded: `chunked` takes `n - 1` items | 123.0–126.0 | `n - 1` → `n` | 828 tests OK | USD 0.008 |
| semver (1.0.26) | Seeded: caret matching uses `>` instead of `>=` | 424.2–427.2 | `ver.minor > minor` → `ver.minor >= minor` | 38 passed | USD 0.004 |

Limitations:
- **Final answers:** the closing summaries are written by the model.
- **boltons:** an intermediate edit wrote back a truncated file, which the model then restored from git. Its final answer says so, and this text is inside the excerpt.
- **Discarded takes:** earlier takes are not used. In those, the terminal theme was unreadable at 360p, the final answer did not show the diff, or the output printed an absolute path of the machine. The four takes above ran from a neutral home folder.

## M3 montage provenance

Source: `demos/user-agent/catalog.json` and `demos/user-agent/media/<task>.mp4` in the harness-policy checkout. Each selected item is `success: true`, `horizon: long`, `benchmark: RoboDojo`, `arm: ARX-X5`. Source intervals are on the original 1×, 25 Hz simulation/video clock, end-exclusive; every excerpt is sped 2×. Edited excerpts are not whole task executions and do not imply the four tasks occurred in one episode. Original recordings and failure evidence are unchanged.

| Task / source file | Source interval (s) | Speed | Notes | Visible action |
| --- | --- | --- | --- | --- |
| cover-blocks.mp4 | 15.24–21.24 | 2× | success tail + 0.22s xfade | Final cover/uncover completion |
| organize-table.mp4 | 13.96–19.96 | 2× | success tail + 0.22s xfade | Desk organize completion |
| sort-dolls.mp4 | 15.44–21.44 | 2× | success tail + 0.22s xfade | Dolls lined up by size |
| make-kong.mp4 | 6.96–12.96 | 2× | success tail | Mahjong kong completion |

Re-cut onto success tails (Codex-located starts; mid-task flashes removed). Final duration 11.360s. Poster SHA256 `d3e364321fb5a4cbcf88bef98e1811b7c3fe12f06f42caa237658fd9f4ff6093`.


Harder long-horizon selection (not the prior toast/laptop/pens/tower set). Same 0.22s dissolve style, 2×, 16:9. Final duration 10.160 s. Poster SHA256 `cdb2de87ec78549883ebbf3d53b2c42de3e9dd097d81af79b508ae5d181de796`.


Smoother edit: slightly longer peaks than the hard-cut pass, then ffmpeg xfade fade 0.22s between segments (no motion interpolation). Final duration 7.400s. Poster SHA256 `97dfcf6fda403317cf5c52bb36a7e823d9aef2d81513dbc4206a40bcf895cc96`. Encoding: 640×360, 25fps, libx264 CRF 18, faststart.


## A3 think-while-acting provenance

Source catalog/trace id `press-number` (`success=true`, `horizon=atomic`, `benchmark=RoboDojo`, `arm=ARX-X5`, `record=trace`, **4 program turns**). Full raw recording sped **1.5×**, center-cropped to 16:9. Final duration 9.160s.

Timeline on the edited clock highlights Harness program adjustment (with evolving lanes):
- **Model**: one planning window at each turn start (rewrites the next program).
- **Programs**: one contiguous segment per adjusted program; boundaries from each turn’s `policy.final_state.step` mapped through source duration ÷ 1.5 ([0.0, 3.18492, 4.748773, 7.723909, 9.16]).
- **Policy steps** / **Camera observations**: ticks from recorded samples when present, otherwise the same 5-step cadence used in other RoboDojo traces across each turn’s step span.

Poster SHA256 `9bc1231ab16683a73af92e87745f15e470a1e7d803b5f1917216e9d6eddaf8c6`.

## A2 one-call provenance

Recorded 2026-11-10 with the Harness 0.81.1 release from PyPI and `deepseek/deepseek-v4.1-flash` for every model call, on the same dressed 1280×720 desktop as M1, captured continuously at 30 fps with the pointer drawn. The TodoMVC React example (todomvc.com) is open in a Chrome app window at 50% page zoom. One `harness run --workspace desktop --physical allow` with this task:

> TodoMVC is open in Chrome. Add these ten to-dos, typing each one and pressing Enter after it: Buy milk, Call the dentist, Book flights, Pay rent, Water the plants, Renew passport, Fix the bike, Email Sam, Plan the trip, Return library books. Then tick the first three as completed. After your first look at the page, do all the adding and ticking in one single program, and look again only at the end to check.

The run made 7 model calls in 77 s (USD 0.009). After one look, the second call wrote one program that clicked the input and then typed and entered all ten to-dos: 21 input steps without another model decision. The clip shows that program. Its final frame has ten rows and the page counter reads "10 items left"; the run's final frame has the first three ticked and "7 items left".

| Source interval (s) | Speed | What it shows |
| --- | --- | --- |
| 4.7–29.2 | 12× | The model writes the program; the list is still empty |
| 29.2–54.4 | 3.5× | The program adds the ten to-dos one by one |
| 54.4–56.1 | 1× | The complete list, until the next model call starts |

All three excerpts are cropped to the 960×540 region at (256, 66) around the list, joined with 0.22 s dissolves and faded out over the last 0.85 s; 640×360, 25 fps, libx264 CRF 18, faststart. Lanes come from the trace, mapped through each excerpt's speed: Model (the program's model call and one lookahead thought during the program), Programs (the program, from its start until the clip ends; a 0.01 s tail of the first program, the look, is at the start), Actions (21 input steps). The video clock is aligned to the trace by the capture's own wall-clock start.

Limitations:
- **Ticks:** the same program also tried to tick the first three rows by finding their boxes in a screenshot. That found none, so the model ticked them in a later program after another look. The clip ends before that.
- **Earlier take:** the first take used a task without the one-program sentence. The model then took 6 calls, typing all ten to-dos in a single `type_text`, and it is not used.

## A4 learn-while-working provenance

Replaced 2026-11-12 with a staged Minecraft 1.16.1 clip. It is a demo of the idea, not a recording of an agent run. The game's coming-soon label on the Multimodal card still applies.

The picture is split in two, 5 s each, 10.000 s in total. The left half ("Practice") plays first and then holds its last frame, dimmed. The right half ("For real") holds its first frame, dimmed, and then plays.

| Half | What happens | How it was staged |
| --- | --- | --- |
| Practice | The player steps off a 23-block scaffolding tower, places water just before landing, picks it up again and turns round | A scripted Mineflayer player on a local offline server. Full health after the landing |
| For real | The Ender Dragon dives at the player, the player is thrown about 12 blocks up, switches to the bucket, places water before landing, picks it up and draws the sword | The dragon is moved along a fixed path every tick. At the pass the script gives the player an upward speed and the server applies damage. No fall damage on landing |

The water landing in both halves is the same code and succeeded in the game: the water is placed from the bucket while falling and decides the landing. The run of events around it is scripted. No model made decisions in this clip.

Timeline (edited clock): authored to match the picture, not derived from a trace. Actions are ticks at the moments visible in the clip (walk, jump, look down, place water, pick up; then switch to the bucket, look down, place water, pick up, draw the sword). Programs cover the practice (0.8–3.2 s), the fight (5.0–6.3 s and 8.5–10 s) and the water landing in the fight (6.3–8.5 s). Model spans mark the start of practice, the review after it and the decision after the landing. The Library lane is empty during the practice and has one bar in the fight, while the learned water landing runs (6.3–8.5 s).

Camera: a spectating 1.16.1 client follows an invisible marker moved every tick, HUD hidden, captured at 960×1080 and 60 fps per half. The halves are graded (the End half is brightened), joined, labelled in Inter 600, and encoded at 1280×720, 30 fps, libx264 CRF 23, faststart. The 1920×1080, 60 fps master and all takes are kept with the recording files. A first-person version was also cut and is not used.

Poster: the clip's first frame, SHA256 `7432066236aae49651ae5b55ec81d393e294af82cb5c23114253954e59c3e257`.
