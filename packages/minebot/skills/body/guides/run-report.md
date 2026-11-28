guide("run-report"): the fields of a run's report; how the did counters are counted.

The fields.
  ended            how the job ended. "an error" when its status is 'error': the code
                   threw without having been told to stop, did not compile, or was
                   refused.
                   Otherwise by what ended it: "by itself", "stopped", "other code took
                   the body", "the body died", "the body was started again"
                   (guide("run-ending")). Absent while the job runs (code_running()).
  result           the code's return value, converted (guide("run-result")); None unless
                   the status is 'done'
  error            the error text; None when there is none
  logs             the last 80 lines logged
  events           the events noted since the job started, of every kind but health, the
                   last 60 (guide("run-events"))
  did              what the code did to the world: below
  channels         the channels the job used: 'move', 'look', 'use' (all three when
                   its unit claimed none; guide("run-channels"))
  cleared          {timers, listeners}: how many timers and how many listeners on the bot
                   the code had left when it ended; they ended with it. None for a job
                   that ended with a restart of the body, and for one that did not start
  seconds          from the job's start to its end, 2 decimals, pauses included
  paused_seconds   the sum of its pauses, 2 decimals

did.
  {dug: {block name: n}, placed: {block name: n}, broke: [item name, ...], moved: n,
   pulled_back: n}
  Counted on the body, by channel, for the running job that holds the channel: dug,
  placed and broke for the job on use, moved and pulled_back for the job on move. While
  a run is paused nothing is counted for it; what the code that took its channels does is
  counted for that code. With no running job on the channel nothing is counted.
  The counters of a run include what the routines it calls do.
  dug      After a bot.dig(block) promise resolves: 1 for the name the block had before
           the dig. Digs that reject are not counted.
  placed   Each time the bot sends the game a block_place packet (the use of the held
           item on a block) while the held item's name is also a block's name: 1 for
           that name. It is counted when the packet is sent, whatever the game then does;
           bot.placeBlock and bot.activateBlock send it.
  broke    The game reports the break of the item in the body's hand (entity status 47
           for the body's own entity): the name of the item last seen in the hand at a
           physics tick is appended, and the event tool_broke {item} is noted.
  moved    At every physics tick the distance from the position of the tick before is
           added, when it is less than 4 blocks (a longer step counts as a teleport and
           adds nothing). Reported rounded to a whole number of blocks. Falling, being
           pushed and being carried count as walking does.
  pulled_back  Each time the server sets where the body is (a position packet from the
           server: Mineflayer's 'forcedMove', guide("physics-server-sync")): 1. The
           server sends one when it does not accept a move the body sent, and at a
           teleport, a respawn and a change of dimension. The event pulled_back
           {position} is noted at the same moment, with or without a job on move.
  While the job runs, `did` (in code_running() and in the state's `doing`, under the
  job's id) is the count so far. For a job that ended with a restart of the body it is
  the count the body last reported for it, or None.

code_running()
  The reports of the jobs in jobs_running, each without `ended`; [] when no job runs. A
  paused job is not among them.

drop_routine(name, why)
  Takes the saved routine `name` off the body (as /skill/remove: its code is kept among
  its versions) and notes routine_removed {name, why}. `why` is required: a call without
  it fails, and so does one for a routine that is not saved.
