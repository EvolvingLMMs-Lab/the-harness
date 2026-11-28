guide("run-state"): the state the body reports: every key, what it holds, when it changes.

How it is made.
  The body's process builds its state every 50 ms from the bot as it is at that moment
  and sends it to the bridge. The bridge answers every reading with the last one it got.
  Before the first spawn, or without the bot's entity, the state is {connected: false,
  ticks}. When building it throws, it is {connected: false, ticks, error}.

Keys built on the body.
  connected        true
  ticks            physics ticks since this body process began
  position         {x, y, z} of bot.entity.position, 2 decimals: the bottom centre of
                   the cell of the feet. The body is 0.6 wide and 1.8 high: it fills
                   that cell and the one above it; its eyes are 1.62 above position
  yaw, pitch       bot.entity.yaw and pitch, radians, 2 decimals
  on_ground        bot.entity.onGround
  velocity         {x, y, z} of bot.entity.velocity, blocks a tick, 2 decimals
  drop_below       blocks from the feet down to the top of the first block with the
                   bounding box 'block' in the column under the body, 1 decimal. Looked
                   for from the block under the feet down 64 blocks, not below y 0. null
                   when there is none in that range or a block of the column is not loaded
  dimension        bot.game.dimension as text: 'overworld', 'the_nether', 'the_end';
                   'unknown' before the game is known
  health, food     bot.health, bot.food
  dead             bot.isAlive is false (guide("run-death"))
  oxygen           bot.oxygenLevel
  level            bot.experience.level; 0 without it
  time_of_day      bot.time.timeOfDay
  world_age_ticks  the world's age in game ticks
  raining          bot.isRaining
  held             the name of bot.heldItem, or null
  armor            the names of the items in slots 5, 6, 7, 8 and 45 (head, chest, legs,
                   feet, off-hand), in that order, empty slots left out
  inventory        {item name: count}, summed over bot.inventory.items(): slots 9 to 44.
                   Armor, the off-hand, the crafting grid and the cursor are not in it
  entities         the entities with a position within 48 blocks, the body's own left
                   out, nearest first, at most 30: {name, kind, category, distance,
                   position}. name is the entity's name, else its username, else its
                   type; kind is Mineflayer's entity.type ('mob', 'player', 'object'...);
                   category is the game data's category of that kind (Mineflayer's
                   entity.kind: 'Hostile mobs', 'Passive mobs', ..., 'UNKNOWN' for
                   piglins and zombified piglins), null where there is none. Neither
                   says whether the entity attacks the body: a piglin angered is
                   'UNKNOWN', a zombie behind a wall is 'Hostile mobs'. distance has 1
                   decimal, position 2
  sensed           {sense name: value} (guide("run-senses"))
  sense_errors     {sense name: why it has no value}
  doing            {job id: its `did` counters so far} for every job that has not ended,
                   running or paused: {dug, placed, broke, moved, pulled_back}
                   (guide("run-report")); {} when there is none
  priority         what a running (not paused) job asks to hold the body with through
                   h.priority or h.atomic at this moment: the name of a node, or true (above every
                   node); null when none asks

Keys the bridge adds (in body()).
  connected        true only when the body is in the world and its last state said so
  deaths           deaths noted since the bridge started
  restarts         times a body that was in the world was started again
  skills           the names of the saved routines, sorted
  libraries        the folder of the libraries the body runs on
  jobs_running     the ids of every running job, in the order they started or were
                   resumed: jobs on channels of their own (guide("run-channels"))
  jobs_paused      the ids of the paused jobs, in the order they were paused
  events_seq       the number of the last event
  window           null without a game window; else {joined, attached, position,
                   said_ms_ago}: whether a game client watches as the body, whether it
                   has had everything since the body's login, where its own player last
                   said it is and how many ms ago

body()
  All keys of both lists, as the bridge has them.

get_state()
  Of the keys above: health, dead, food, oxygen, level, held, armor, inventory, position,
  velocity, drop_below, yaw, pitch, on_ground, dimension, time_of_day, raining, deaths,
  sensed, sense_errors, priority, entities, connected, restarts.
  Added to them:
  routines         the bridge's `skills`
  jobs             the tags of the caller's code that is running or paused
  here, space      [x, y, z] of position; the dimension
  attempt          {number, clean, deaths, advancements}
  happened         the last 8 events of the kinds death, respawn_or_dimension,
                   body_restarted (guide("run-events"))
  screen, step, step_limit, ended     of the run, not of the body
  ticks, world_age_ticks, doing, jobs_running, jobs_paused, events_seq, window and
  libraries are in body() only.
  While the body is not connected, the keys keep the values of its last reading and
  connected is false.
