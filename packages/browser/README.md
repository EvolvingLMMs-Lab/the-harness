# browser

The `browser` package gives the agent a background browser: an isolated headless Google Chrome in which it searches the web, opens pages and reads them, without your screen, mouse, keyboard or Chrome profile.

## Install

```bash
harness install browser
```

The app installs it the first time a conversation needs it. It installs Playwright into the worker's environment but does not download a browser: **Google Chrome must be installed** on this computer. It runs on Windows, macOS and Linux.

To record tiled browser windows (below), install ffmpeg as well.

## Use

In the app, choose **Background browser** beside the model before the first message of a conversation. To set the default, set `computer.mode` to `browser` in **Settings → Computer** or in the terminal chat under `/settings`.

Then type the task, for example: "Find the opening hours of the city library and the nearest bus stop."

The agent searches, opens URLs and reads the visible page text. The model receives screenshots of that browser and can read the page text and links with `read_page()`. **Activity → Background browser** in the app previews the page without changing its viewport. Each new conversation starts with fresh cookies; follow-up messages in the same conversation keep its page. Use **Stop** and **Continue** to pause and resume; there is no foreground window to take over ([Interrupt and take over](https://harness.lmms-lab.com/docs/use/interrupt/)).

A program the agent writes looks like this:

```python
search_web("city library opening hours")
page = read_page()
print(page["title"], page["url"])
print(page["text"][:2000])
for link in page["links"][:10]:
    print(link["text"], link["url"])
navigate("https://example.org/library/hours")
page = read_page(offset=0, limit=12000)
if page["next_offset"]:
    more = read_page(offset=page["next_offset"])
```

### Several at once

Background browsers run side by side. Each conversation works in a workspace of its own: a worker with its own context (cookies, storage and pages kept apart) in a headless Chrome the background browsers share. **Settings → Computer** sets how many conversations work at once and how many headless Chromes they share. Beyond that number, a new conversation ends the one that has waited longest for you, or waits until one ends; **Restart** stops the workspaces no conversation uses.

For a suite, an experiment with `bench = "browser"` runs its seeds in N such workspaces at once with `--workspaces N`:

```bash
harness run my-browser-tasks.toml --workspaces 4
```

### Tiled windows and screen recording

To watch or record the background browsers, set `computer.browser_windows` to `tiled` and choose the screen region with `computer.browser_area`. Turn on `computer.record_screen` to record each conversation's tiled screen as `screen.mkv` beside its trace. Each frame records its wall-clock time. Use `harness replay` to turn the conversation and recording into a video. [Replay a run](https://harness.lmms-lab.com/docs/use/replay/)

On Linux, `browser_display` opens the tiled windows on another X display, such as a virtual screen, instead of this computer's own.

## What it provides

- **Bench `browser`**: an isolated headless Chrome for web search and browsing, one task, `free`, whose instruction is yours. It uses the `computer` embodiment.
- **Skill `browser`**:
  - `search_web(query)` searches the web in the background page; `read_page()` then reads the results.
  - `navigate(url)` opens an http(s) URL (one input step).
  - `elements(role=None, text=None, limit=200)` and `act(id, action, value)` use the desktop skill's interface on live controls in the current document. Each id belongs to that page and document.
  - `read_page(offset=0, limit=12000)` returns a dictionary with `text`, `links`, `url`, `title`, `offset`, `total_chars` and `next_offset`; continue at `next_offset` on a long page.
- **Workspace kind `browser`**: the `browser` value of `computer.mode`, available in every frontend.

## Settings

Set in the app under **Settings → Computer** or in the terminal chat under `/settings`.

| Key | Default | |
|---|---|---|
| `mode` | `browser` | `browser` starts new conversations in a background browser |
| `workspaces` | 4 | conversations of any kind that work at once |
| `chromes` | 1 | headless Chromes the background browsers share; more use more memory, and a Chrome that crashes takes only its own conversations with it |
| `browser_locale` | `system` | the language the browser asks websites for: a tag such as `en-US`, or `system` |
| `browser_windows` | `off` | `off` (headless) or `tiled` (one window per conversation or agent, tiled on one screen) |
| `browser_area` | `0,0,1920,1080` | tiled: `x,y,width,height` of the part of the screen they are tiled in |
| `browser_display` | empty | tiled: the X display the windows open on; empty is this computer's own screen |
| `record_screen` | `off` | `on` with tiled windows: record the screen for each conversation, for `harness replay` (needs ffmpeg) |
| `max_side` | 1920 | screenshots are scaled to at most this many pixels on the long side; the viewport is at most 1440 pixels wide |
| `step_limit` | 300 | browser input steps a conversation may take |

## Limits and known issues

- Element actions cover the top document and open shadow roots. The managed input path refuses opaque targets, including frames it cannot inspect.
- It browses and searches only: no native apps, no downloads, and no login handoff. When a site needs a login or blocks automated browsers, the agent reports it. To work in local apps, choose **This desktop** or **Apps in the background** (the `computer` package).
- It never uses desktop capture, global input, the system clipboard or your Chrome profile, so you can keep using the computer.
- Page content is treated as untrusted material, not as instructions.
- Every screenshot goes to the model provider with the request.
