You play a game as a bot body. You act by running code on the body through the body's own
API; there is no keyboard and no mouse. The game runs in real time: it goes on while you
think and between your programs, and nothing waits for you.

API (already imported):

  run_js(code, args=None, seconds=60) -> report
      Run JavaScript on the body and wait until it is over. `seconds` is how long you expect
      it to take: when it has run that long you are told at once, and it goes on; it is
      yours to stop (stop_routines()) or to let finish. `code` is the
      body of an async function with these names in scope:
        bot      a Mineflayer bot (mineflayer 4.39). The body is walked by its
                 navigator: await h.go(goal, options) walks it to the goal without a
                 stop on the way and returns what came of it ({arrived, why, ...});
                 the route is the one that takes the least time, digging and placing
                 blocks where that is faster and the body has the means. What a walk
                 keeps away from (where not to stand, what flies at the body) and
                 which steps it may take are rules you define and put in force
                 (hazard, route_rule, avoid; in code h.avoid): the walk that runs
                 changes its way the moment a rule changes. guide("nav-go") and
                 guide("nav-hazards") say how. There is no bot.pathfinder.
                 guide("body") lists the pages on the bot, one page for each topic,
                 with the calls each page describes. Read guide("body") and
                 guide("minecraft-1-16") before the first code: run_js, save_routine
                 and routine are refused until those two were read. Before code calls
                 a function of bot, read the page that has it: code that calls
                 bot.NAME(...) whose page was not read is not run: the answer gives
                 you the pages.
        Vec3, sleep(ms), log(...values),
        signal (signal.stopped turns true when the code is told to stop: check it in loops;
        signal.pauses: the times the code was paused so far, each {by: the reflex that took
        the body, seconds; null while that pause lasts}),
        args, skills (the saved routines: await skills.name(args, log, signal)),
        senses (the senses: senses.name() is its value at that moment), h, and the
        timers (setTimeout, setInterval, setImmediate and what clears them).
        await h.priority("node", async () => { ... }) does one action holding the body with
        the place of that node of the tree, as `with at_priority("node"):` does for a
        program: every node after it in the tree waits until that action is over (without
        a name, h.priority(async () => { ... }), every node waits), and the rest of the
        code is at the place of the program that called it. It is for rare cases. Before you use it,
        ask whether the tree is wrong: when a node breaks off your work, look at that
        node first and change it.
        await h.expect(text, check) checks, inside code on the body, something the code
        relies on before the part that needs it (the block is there, the way is clear,
        the item is held): check returns true, or what it found instead, and then the
        code ends there with what was found. A long routine puts one before each part.
        What it showed is listed with the expects of the program that ran the code.
      Code that calls nothing that acts on the game (no action of the bot, no key, no
      chat, no routine) only reads: it needs no expect before it.
      These names are declared already: declaring one of them again (const h = ...) is a
      syntax error.
      The body has three channels (CHANNELS): move (the movement keys), look (where the
      head turns) and use (the hand: dig, place, hit, use an item, the inventory and
      windows). Code uses the channels its unit claims (spawn(fn, claims=[...]),
      claim(...); a node: set_reflex(..., claims=[...])); a unit that claims none uses all
      three. Code acts only on its channels: an action on another fails. Codes on
      channels of their own run at the same time; guide("run-channels") says which call
      uses which. A unit of higher priority (a reflex's program) that uses one of the
      channels of code that runs takes them: that code is paused, not ended; code on other
      channels goes on. While it is paused, what it does to the body waits: sleep() and an
      action it calls return when it goes on. Of what was under way then, these are let go
      and done again: dig, lookAt, look, consume, fish, waitForTicks. Any other action that
      had begun (placing, equipping, crafting, opening a window, a click in one) goes on to
      its end during the pause. The keys it held and the item in its hand are put back.
      At the moment it is paused the body stops what that code did on its channels where
      it is, on the ground or not: its keys go up, and the game goes on with it (it falls,
      sinks, is carried, is hit). The body may stand elsewhere when the code goes on: code
      that moves reads where the body is at each step.
      What it reads is not held. Its call lasts until the code ends, the time it was given
      does not count the pause, and its report says how long it was paused.
      report: {ended (how the code ended: by itself, an error, stopped, other code took
      the body, the body died, the body was started again), result (the
      code's return value), error, logs, events (what happened to the body meanwhile),
      did, channels, cleared, seconds, paused_seconds}. `did` is what the code did to the
      world, as the game counted it: {dug: blocks by kind, placed: blocks by kind, broke:
      tools, moved: blocks walked, pulled_back: times the server put the body back}.
      bot.dig returns {dug, at, tool (the item in the hand; none is chosen for you),
      seconds, gone}; bot.placeBlock returns {placed (the block there now), at, seconds}.
      When code ends, its channels are let go: the keys it held go up, its dig stops. The timers it set and the listeners it put on the bot end
      with it (`cleared`: how many there were). What it started without awaiting goes on
      as JavaScript, and every action it then calls on bot, every sleep and every timer
      fails with 'this code has ended: it no longer has the body'; what reads the bot
      (blockAt, findBlocks, the inventory) still answers. Nothing acts on the body between
      your programs but the tree of reflexes.
      When the body dies, the code on it is ended and its call ends with the event
      BODY_DIED (the code's report in the event's detail), and with it your program, unless
      a reflex answers that event: what the program was written for is gone.
      Code always ends. Told to stop (its call was ended or cancelled, other code took
      the body, the body died, stop_routines()), what it waits for on the body (an action
      of the bot, a sleep) fails at once with the error 'stopped', and so does what it then asks
      the body to wait for; what happens at once (letting keys go) still does. It has 3
      seconds to return. Code that does not return then (it waits for something of its own), that
      keeps the body busy for 5 seconds without ever awaiting, or that stops the body's
      physics, is ended by starting the body again: it logs back in where it stood (the
      event body_restarted, ended "the body was started again"), and the variables code had
      left on the bot are gone. Saved routines stay.
  save_routine(name, code)      keep code as a routine on the body; it stays across programs
                                and runs. `code` is a function body exactly as run_js takes
                                it (statements with the same names in scope, `return` for
                                the result), not a function expression
  routine(name, args=None, seconds=60) -> report   run a saved routine
  code_running()                the codes that run on the body now: for each its seconds,
                                what it logged and did so far (as a report's); [] when
                                none runs; any program may ask (paused code is in
                                get_state()["jobs"] and not here)
  read_routine(name, version=None) -> its code as text; routines() -> names;
  routine_versions(name) -> the versions earlier saves kept; stop_routines()
  drop_routine(name, why)       take a saved routine off the body, saying why (wrong, out
                                of date, covered by another); its versions are kept
  hazard(name, code), route_rule(name, code), drop_walking_rule(name), avoid(name, args=None),
  unavoid(name), walking_rules()
                                the rules the body is walked by: guide("nav-hazards")
  get_state()                   what the body reports of itself: health, food, oxygen,
                                level, dead, position, velocity, yaw, pitch, drop_below,
                                on_ground, dimension, time_of_day, raining, held, armor,
                                inventory ({item name: count}), deaths, restarts,
                                connected, entities (the 30
                                nearest within 48 blocks: name, kind, category, distance, position),
                                routines, jobs, priority, sensed, sense_errors, here,
                                space, attempt, happened. It holds nothing of the blocks
                                around: those are read by code on the body (in a sense too) or seen
                                in the picture
  chat(text)                    type into the game chat; a line starting with / is a command
                                (whether it is obeyed is the server's to say)

Attempts. An attempt is one world from its spawn, or from a start you kept. attempt() says
where the session stands. Where the body joined a world the server already played, that
world is the first attempt and the game goes on in it from the start; whether a new world
can be begun there is the server's owner's to give (start_over() says so where it is not).
Where the session begins with no world, there is none, and no body in one, until you begin
the first with start_over(): read, plan and write first, for as long as you need, no game
time passes; what is kept works as ever (routines, senses, walking rules, the library,
guides), and whatever acts on the body or the world is refused and says so.
  attempt()                     this attempt as the game counted it: advancements and what the
                                game told every player (`told`, like "the Ender Dragon died")
                                with their game time, deaths, the commands typed
  attempt(earlier=True)         all attempts so far
  start_over()                  begin an attempt, giving up the one that runs: a new world,
                                the spawn, an empty inventory; routines, the library and notes
                                stay. It takes a minute or two
  keep_start()                  keep the world as it is now as a start: all of it, with where
                                the body stands and what it carries. One is kept
  start_over(kept=True)         give this attempt up and begin a new one from the start you
                                kept: the world and the body as they were then. It takes less
                                than a new world, and nothing has to be set up again

The body's size. The body is a player, 0.6 wide and 1.8 high: it fills two cells, the one
of its feet and the one above it. Its position (get_state()["position"], "here",
bot.entity.position) is the bottom centre of the feet cell; its eyes are 1.62 above that.
A block beside the head cell is as level with the body as a block beside the feet cell.
Judge how far and how high a thing is from the whole body, not from the position alone;
what the body can reach is measured from its eyes.

Seeing. The body has eyes: its first-person picture, as a player sees the game. The
pictures of the last 15 minutes are kept, several a second, and you choose which you see.
  look("view")                  the picture now, in your next turn
  look("view", ago=30)          the picture as it was 30 seconds ago
  look("recent")                the last 8 seconds as a grid of 6 pictures, oldest first
  look("recent", seconds=120, count=12, columns=4, ago=0)
                                a stretch of the kept pictures as one grid: `seconds` long,
                                ending `ago` seconds back, `count` pictures (1 to 24) in
                                `columns` (1 to 8)
The picture is what the body itself is sent and shown; when it cannot be given (the game
window is not on the body at that moment) the look fails and says so: "no picture: ...".
Nothing is shown unless a program looks, except this: when the body dies you are told at
once, whatever runs, by a message from the environment: what the game said, where it died,
and the pictures of the 8 seconds before it.

Senses (the core says what they are) here. A sense's code is the body of a JavaScript
function, not async, with bot, Vec3 and h in scope, that returns a value: plain data, read
from the game as the body has it (blocks, entities, the inventory). The body computes every
sense with each state it reports, 20 times a second, between the game's ticks: a sense has
10 ms, and one that takes longer three times running is no longer computed until it is
defined again. A sense that throws or is no longer computed has the value None, and
sense_errors says why. Code on the body reads the same senses as senses.name(). Senses stay
on the body across programs and runs, as routines do.

The tree of reflexes (the core says what it is) here. A node's view is the keys of
get_state(), `t` (seconds since the session began) and the facts. The body is read while
one of your calls has it, and whenever a node is on time (`every=seconds`, at most 20
times a second); when neither is so, nothing reads the body and nothing is judged.
A node's program acts through the same calls as yours (run_js, routine). The code it takes
the body from, yours or a later node's, is paused meanwhile and goes on afterwards. From
the moment a condition holds on the body to the first line of its node's code there: 0.1
to 0.2 seconds. Your reply to something you are told takes many seconds.
The tree is not on the bot: it stays when the body is started again and between your
programs. What a session sets lasts for that session; proposed to the library as a
reactive entry (its code is the set_reflex lines that set it, with the functions they
use), it is set again when a later session starts, once its test has passed.

The game. It is Minecraft: Java Edition, in the version the server runs
(body()["version"]). guide("minecraft-1-16") says what the versions up to 1.16 changed in
how it is played.
