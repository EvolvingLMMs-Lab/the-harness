# minebot

A bot body for Minecraft: Java Edition servers. The agent joins a server as a player and
acts through the body: it writes JavaScript that runs on the body in the game (the body is
a [Mineflayer](https://github.com/PrismarineJS/mineflayer) client), keeps what works as
routines, sets reflexes that act on time while it thinks, and, where a game window is set
up, looks at what the body sees.

**NOT AN OFFICIAL MINECRAFT PRODUCT. NOT APPROVED BY OR ASSOCIATED WITH MOJANG OR MICROSOFT.**

This package contains no part of the game and downloads none: no server, no client, no game
files, no data packs. It joins a server that is already there, one you run yourself or one
you are allowed to join. Putting a bot on someone else's server is subject to that server's
rules; that is the responsibility of whoever runs the bot.

## What it needs

- **A game server to join**: its address. Any Minecraft: Java Edition server the Mineflayer
  version this package pins can speak to. The package was tried on 1.16.1 and 1.20.4;
  [what was tried](#what-was-tried) says how far.
- **Node** and the body's libraries: installed by the package itself on first use, under
  the harness's own folder (`harness minebot setup` does it ahead of time). Node comes from
  nodejs.org, checked against the release's checksum; the libraries are pinned by
  `body/package-lock.json`.
- **For pictures (optional)**: your own copy of the game and a launcher instance for it
  ([The game window](#the-game-window)). Without a window the body works from what it
  reports of itself and of the world around it, and has no pictures.

## Use it

```bash
harness install minebot
harness minebot setup                               # Node and the body's libraries, once
harness minebot check --set host=127.0.0.1          # the body's own checks against your server
```

In a conversation (the terminal, the app, `harness run`), choose the workspace `minebot`:

```bash
harness --workspace minebot
```

The package starts the body beside the server the settings name and stops it when the
conversation's host closes.

For a long session that learns and keeps what it learned in a folder of its own, use a run:

```bash
harness minebot run first --task task.txt --model MODEL --minutes 240
harness minebot run second --from first --task task.txt     # goes on with what first learned
harness minebot run proof --verify first --task run.txt     # one attempt with what it learned
harness minebot run --tell "leave the cave before night"    # say something to the run that runs
harness minebot run --continue first --message "go on"      # one more turn after its turn ended
harness minebot table first                                 # what the game recorded of it
harness minebot stop
```

`task.txt` is the task in your own words. A run's folder (under the harness's data folder,
`minebot/runs/<name>/`) holds its library, its routines, its trace, the body's events and
`setup.json`, the record of what it was started from. `harness minebot run --help` lists
the rest (a run again without a model, a run from a script).

A learning session keeps the code the agent writes only where the harness admits it: see
the setting `learning.admission` of The Harness.

## Settings

The section `[minebot]` of the app's settings (`/settings`, or `~/.harness/config.toml`);
every command takes `--set KEY=VALUE` for one use.

| Setting | |
|---|---|
| `host`, `port` | the server the body joins (default `127.0.0.1`, `25565`) |
| `version` | the game version the server runs; empty asks the server |
| `username` | the body's player name, or the account it signs in with |
| `auth` | `offline` (the server checks no account) or `microsoft` |
| `rcon_port` | the server's command port, where its owner gives the body one |
| `window`, `launcher`, `instance`, `window_title` | the game window |
| `bridge_port`, `worker_port`, `view_port` | the local ports of the body's own processes |
| `start_over`, `keep_start`, `kept_info` | your own commands that make and keep worlds |
| `dig_rules` | a file with the dig times of your server's version |

**Signing in.** With `auth = "microsoft"` the body asks you to sign in once: the command
prints an address and a code, you sign in in your browser, and the tokens are kept on this
computer under the harness's data folder. The package never sees a password.

**Commands of the game.** `chat("/...")` types a command as any player does; whether the
server obeys it is the server's to say, and its answer comes back in the chat.

**Buckets.** `bot.fillBucket` and `bot.pourBucket` go by the server's command port (RCON).
Give the body one with `rcon_port` and the password in `$MINEBOT_RCON_PASSWORD` (never in a
file); without one these two calls say so and a bucket is used as any held item is.

**New worlds.** The worlds of a server are its owner's. Where you run the server, you can
give the body a command of your own that makes a new world and has the server play it
(`start_over`), and one that copies the world as a start to begin from again (`keep_start`);
the agent then begins its attempts itself (`start_over()`, `keep_start()`). `start_over` is
called with `--kept` for a copy of the kept start and prints `{"world": "<name>"}` as its
last line; `keep_start` is called with `--record JSON` and prints `{"seconds": n}`;
`kept_info` prints that record again. Without them the agent is told that the server's
world is not the body's to begin anew.

**Dig times.** The body's dig times and best tools come from the game data of its
libraries, which differ from some servers for some blocks (the body then picks a slower
tool or stops a dig early). `dig_rules` names a table for your server's version in the form
`body/dig_rules.js` reads; none comes with this package.

## The game window

The pictures the agent looks at are your own game's: a real game client that joins a local
port of the body's bridge and is sent what the body is sent. It needs your copy of the
game, [Prism Launcher](https://prismlauncher.org/) and an instance of yours with Fabric
Loader on the game version 1.16.1.

```bash
harness minebot window setup --launcher "C:/path/to/prismlauncher.exe" --from my-fabric-1.16.1
```

This copies your instance to one of its own (without its worlds and mods), puts one mod
into it (`window/`: its source, and the jar built from it) and turns the window on. The mod
does one thing: it joins the bridge's port once the game has loaded. From then on the
package starts that instance with the body, moves its window out of the foreground and
captures it.

Limits of the window: Windows only, game version 1.16.1 only, one window. On other systems
and versions set `window = "off"`.

## Limits

- One body on a computer at a time: the body's processes use fixed local ports (the
  settings).
- The body is one player: nothing else may use that player name on the server while it runs.
- macOS has not been tried.
- `harness minebot check` moves the body a little and restarts it several times; with
  `--operator` it also kicks and kills the body by command.

## What was tried

On Windows, against servers of the game as it is sold, without accounts (`auth = "offline"`).
On Linux, without a window, the install, the checks (9 of 9) and a scripted run were tried
against the 1.16.1 server.

| | Game 1.16.1 | Game 1.20.4 |
|---|---|---|
| Joins, reads its state, runs code, routines, restarts | yes | yes |
| `harness minebot check` | 9 of 9 | 9 of 9 |
| Walking and digging (`h.go`, `bot.dig`) | yes | yes; one walk of five did not end within its 90 seconds |
| A command where the body may use none | the server's own words come back | the same |
| A model's practice run (`harness minebot run`) | yes | not tried |
| The game window | yes | no |

Not tried yet: `auth = "microsoft"` against a server that checks accounts, the game window
beside such a server, and macOS.

The page `guide("minecraft-1-16")` the agent reads describes the game up to 1.16; on a
later version the agent has that page and what the body reports. What the body's own
walking and its fixes to the Mineflayer client assume was written against 1.16.1.

## What is in it

- `body/`: the bridge and the body (Node): the processes that hold the Mineflayer client
  and run the agent's code on it, and the body's own walking (`nav.js`).
- `skills/body/`: the agent's calls on the body, and the pages (`guides/`) that say how the
  body's libraries are used.
- `benches/mineflayer/`, `embodiments/mineflayer/`, `kinds.toml`, `prompts/botbody/`: the
  worker, the kind `botbody` and its prompt.
- `harness_minebot/`: installing, starting and stopping, runs, checks, the workspace.
- `window/`: the window mod's source and jar, and the scripts that start the window.

The body's walking is its own (`body/nav.js`: the cost of a step, what is forbidden, how the
keys are chosen). The search itself and the base rules of which cell leads to which are
[mineflayer-pathfinder](https://github.com/PrismarineJS/mineflayer-pathfinder)'s; `body/package.json`
pins that project at a commit of its own repository.
