guide("nav-cost"): what a route costs. The only unit is seconds.

A route is the string of steps that is expected to take the least time. Going round,
digging through, bridging over and climbing down and up are compared by that alone.

What a step is expected to take.
  walking, sprinting      the distance at the game's speed: 4.317 blocks a second walking,
                          5.612 sprinting (sprinting needs food above 6)
  in water                the distance at 2.2 blocks a second
  a step up               as walking a block: a body that runs jumps up on its way
  a drop                  the longer of walking its distance and falling: sqrt(2 * blocks /
                          32) s (the two go on at once)
  digging a block         the block's dig time by the game's own formula, with the fastest
                          item for it that the body has and may still use (the bare hand
                          when none is faster); 0.25 s more when the item it needs is not the
                          one in the hand (the hand as it is now, for the first dig)
  placing a block         0.3 s; 0.25 s more when it is placed under the body in a jump
  These are corrected by what the steps really took: for walking, digging and placing the
  navigator keeps the ratio of real to expected time of the last steps of that kind
  (between 0.5 and 4) and multiplies by it, the expected time taken without the ratio.
  Soul sand, hunger, water over the feet show up there.

What is left, as the search guesses it.
  The search is greedy: it goes first where what it has spent and four times what it
  guesses is left are least, and takes the first route it finds to the goal. What is left
  is the distance across to the goal at a run; to a place, not its height (a block up or
  down on the way costs about what walking it does).

What the body has is a limit, not a price.
  blocks to place         every full block in the inventory that does not fall (no sand, no
                          gravel) can be placed. A route needs no more placements than the
                          body has such blocks.
  tools                   a tool is counted for as many digs as it has uses left; a route
                          whose digs would use a tool up is searched again with the next
                          fastest item for the rest, down to the bare hand.
  The route is searched again when the inventory changes while a route that digs or places
  is walked (a tool broke, the blocks ran out, something was picked up).

What is dug and what is not, by the terrain rules.
  A block is not dug when a liquid is beside or above it, when a block that falls or an
  entity is above it, or when it cannot be dug at all (bedrock, a chest). The liquid is
  looked for again as the walk digs the block: lava flows, and where it has come beside
  the block since the route was searched, the step fails and the route is searched again.
  A cell with lava (a flow too), fire, a berry bush, a wither rose, a campfire, a magma
  block or a cactus is never stepped into or onto, and the walk keeps the body's box from
  reaching one: a cell beside the way burns the body as well.

Everything else is yours to say.
  Whether a block is worth keeping, whether a tool is to be spared, whether a kind of step
  is not to be taken where the body is now: a route rule says it, and none is there until
  you define one (guide("nav-hazards")).
