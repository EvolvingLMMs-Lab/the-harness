guide("run-events"): the events the body and its bridge note: kinds, fields, when.

Every event.
  seq      its number, counting up from 1 since the bridge started
  t        when the bridge got it, ms since 1970
  kind     one of the kinds below
  age      (events from the body) the world's age in game ticks when it was noted, or
           null before the game has sent its time
  The bridge keeps the last 2000 events. A run's report holds, as `events`, the last 60
  noted since the run started, of every kind but health.

From the bot.
  joined {dimension}                the first 'spawn' of a body process
  respawn_or_dimension {dimension}  every later 'spawn' of that process: after a respawn
                                    and after a change of dimension
  chat {message, where}             every line the game shows (Mineflayer's 'messagestr'):
                                    the text, cut to 300 characters; where is 'chat',
                                    'system' or 'game_info'
  command {text}                    the bot sends a chat line that starts with '/': the
                                    line, cut to 100 characters. Noted when it is sent,
                                    whatever the game answers; bot.chat from code and the
                                    Python chat() both count
  health {health, food}             every health packet of the game
  hurt {health}                     Mineflayer's 'entityHurt' for the body's own entity
  death {position, message}         guide("run-death")
  collect {}                        Mineflayer's 'playerCollect' with the body as collector
  tool_broke {item}                 the game reports the break of the item in the hand
  window {open, type}               a window opened (open true) or closed (open false):
                                    a chest, a furnace, a crafting table; type as
                                    Mineflayer names it ('minecraft:furnace')
  pulled_back {position}            the server set where the body is (Mineflayer's
                                    'forcedMove': guide("physics-server-sync")); position
                                    is where it put the body. Counted in the did of the
                                    running job on move (guide("run-report"))
  kicked {reason}                   the game kicked the bot; reason cut to 300 characters
  error {message}                   the bot's 'error' event; also failures of the body's
                                    own steps ('respawn: ...', 'chat: ...', 'inventory slot
                                    from the server: ...')
  end {reason}                      the connection closed; the process ends 50 ms later

From the body's process.
  listener_error {on, message, again}   a listener of any emitter threw or rejected: `on`
                                    is the event's name, message the first 200 characters.
                                    The first time for an (event, message) pair it is
                                    noted without `again`. Repeats within 5000 ms are
                                    counted and not noted. The first repeat after 5000 ms
                                    is noted with again: the number since the last note.
                                    The table of pairs is emptied when it passes 200
  uncaught {message}                an exception nothing caught (a timer callback that
                                    throws); the process goes on
  unhandled {message}               a promise rejected with nothing handling it (a call
                                    made without await that fails); the process goes on
  skill_load_error {name, message}  a saved routine did not compile
  sense_load_error {name, message}  a saved sense did not compile at the process's start
  user:KIND {...data}               h.note(KIND, data) (guide("run-helpers"))

From the bridge.
  over_time {job, seconds}          a job has run the time its call gave it; once per job
  job_paused {job, by}              guide("run-pause"); by: who paused, or null
  job_resumed {job, paused_seconds}
  body_restarted {why}              guide("run-restart")
  body_gone {why, times}            a body process that was not in the world ended
  window_joined {name}, window_left {reason}, window_error {message}
                                    the game window that watches as the body came, left,
                                    had a connection error
  bridge_error {message}            an error inside the bridge

What reaches the caller beside the report.
  get_state()["happened"]: the last 8 events of the kinds death, respawn_or_dimension
  and body_restarted, each {kind, t (seconds since 1970)} with dimension, message or why
  when the event has them.
  A death and an over_time are also told to the model as messages when they are noted.
