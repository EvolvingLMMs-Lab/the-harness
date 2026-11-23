guide("nav-steps"): what the navigator does at every tick of a walk.

At each physics tick (20 a second) while a walk lasts, the route is checked and the keys
of the tick are pressed.

The route: a string of cells from where the body stands to the goal.
  A body in the air (it jumps or falls: not on the ground, not in water or lava, not on a
  ladder or a vine) stands in no cell yet: no route is searched until it stands, and the
  keys are up meanwhile.
  It is searched over the loaded world when the walk begins, and again when it no longer
  holds:
    - no way of pressing the keys makes the next step from where the body stands, and the
      body is not at that step (it was thrown, or came down elsewhere): see below
    - the server put the body back (the event pulled_back)
    - a hazard or a route rule came into force or went out, or a zone covers other cells
    - a means the rest of the route uses is gone: the last block to place, where blocks
      are still to be placed; a kind of tool, where blocks are still to be dug. More items,
      or the same items moved (to the hand, between slots), change nothing
    - the goal moved and the route no longer ends at it (the body walks on along the
      route it has while the new one is searched)
    - a step failed
  A search has 25 ms of a tick and goes on in the next; the keys are up meanwhile. After
  0.3 s the best part found is walked, where it gets clearly nearer, and the search begins
  again from its end. A search is given up after 0.5 s and 0.25 s for each block the goal
  is away, 8 s at most.
  A goal that moves and is in a straight walkable line from the body is not searched for:
  the cells of that line, from the body to where the goal is now, are the route, taken
  anew each tick. The keys along it are chosen as along any route.

The keys of this tick.
  The head is turned to the next cell of the route (several cells ahead where the way is
  plain walking in a straight line). Within 0.6 of the point it goes to (falling onto a
  lower cell, coming up onto a higher one, going by a middle) it keeps the direction of
  the step itself: the body does not turn round to stand on a middle. Before a step down
  it is turned to the middle of the lower cell while the body stands on the ground above.
  A middle the body has gone by along the step it is never turned back to, unless the
  body has to stand on it.
  The keys are chosen by running the game's own physics ahead from the body as it is now.
  A way of pressing them is: forward at a run (food above 6) or at a walk, with a jump at
  one tick (now, or 1 to 12 ticks from now) or with none; or forward let go of at a tick
  (12 ticks from now down to now), as a player lets go of it once over an edge so as not
  to go on past a place a block wide below. A way holds when, pressed until
  the step is made and with no key pressed after that until the body has come to rest,
  the body then stands on the route with the step still made, its cell never forbidden,
  never off the route or below it, and its box (0.6 across, 1.8 high) in a cell with lava
  (of any level: a flow too) or fire for no more ticks than if no key were pressed at all
  (over the same 2 s). So a body out of harm takes only ways that touch none of it; a
  body already in it (fire under its feet) takes the way out of it soonest. The ways are
  tried in this order and the first that holds gives this tick's keys (of several that
  touch what hurts, the one that touches it least):
    - at a run before at a walk
    - with no jump, then a jump now, a jump one tick from now, and so on
    - last, forward let go of at a tick, the latest first
  Where the step after the one being made leaves the ground (a gap, a block up), the ways
  are judged up to that step first, so that its jump can come while this step is still
  being made; if none holds that far, up to the step being made.
  So nothing is written down about where the body jumps or slows: it jumps at the tick
  from which the jump lands on the cell, early at a run where the landing is short; it
  walks where a run would carry it past a cell it has to stand on or across a hole it
  has to step down into.
  That a way holds is the one judgement of whether the route still holds: the physics is
  run in the world as it is now, so a block put in the way since the route was searched
  (by the walk itself too), a landing elsewhere or a hit all count.
  No way holds and the body stands (on the ground or in water): the route no longer holds
  from here. Where the body is at the step (in the cell it goes from or to), the step has
  failed at once, with "no pressing of the keys makes this step from where the body
  stands"; elsewhere the route is searched again from where the body is.
  A jump across a gap (2 to 4 cells straight ahead, the same height, a cell up or down) is
  one the body makes from a run: the route holds it only where the run-up it needs can be
  taken (by the same physics: from rest at the middle of the take-off cell or of a cell up
  to 3 behind it, forward at a run, up into the jump at the edge, it lands on the far
  cell; the cells behind are cells to walk on that no rule forbids). A body that comes to
  the take-off at speed along the jump just jumps. One that does not (it came in from the
  side, or stood) and for which no way holds takes that run-up first, to the cells behind
  and back (the event nav_route says "a run-up of N cells before the jump"), then jumps.
  No way holds while the block of a bridge ahead is still on its way: forward is pressed,
  at a run or at a walk, for as long as the body could still stop on the route after this
  tick, by the same physics; when it could not, no key is pressed. So the body comes up to
  the edge and waits there for the block.
  No way holds and the body is in the air (thrown, or a jump missed): the other keys named
  below (forward, back, left, right, with and without jump, held for some ticks or to the
  end) are run through the same physics, and those that have the body come to stand on
  the route are pressed (the report counts these ticks as rescued).
  In water the jump key is held for a step that does not go down (swimming up).
  Where the way chosen would have the body met by something that flies (a hazard's
  `incoming`, each moved ahead by its own velocity tick by tick), other keys are tried in
  its place (forward, back, left, right, with and without jump): each is run through the
  game's own physics for a few ticks, the chosen way after that, until the body stands.
  They are compared by, in this order:
    - how often what flies meets the body
    - whether the body still stands on the route, out of lava, fire and forbidden cells
    - the seconds from where it stands to the route's end
  So the body sidesteps, speeds up or waits for what flies and goes on along the same route.

A step of the route.
  It is made when the body is at the cell's height (on the ground there, unless the step
  is plain walking; a step of plain walking also above it by no more than a jump rises,
  1.3: the body in the air there is on its way to a later step) and has come to the
  cell's middle along the step, or past it: within
  0.75 of the middle, or beyond it. Only where the body has to stand exactly is the middle
  itself asked for, within 0.35: a cell before a dig or a block placed under the body, and
  the last cell of a route to a goal that does not move.
  A goal that is a point {x, y, z, range}: from the last cell the body walks straight to
  the point, head to it, forward at a walk for the fewest ticks after which (by the same
  physics) it comes to rest within range; then the walk is over. Where no number of ticks
  does and the body stands still, the walk ends with "the body cannot come within R of the
  point: it stands D from it across".
  a dig             the keys go up; an item that digs the block faster than the bare hand
                    is put in the hand (the fastest the body has and the walk may use);
                    where none is faster the block is dug with what the hand holds, which
                    wears a tool held there (an item named in the walk's keep is put
                    away first); the block is dug; the step fails when the game still
                    has the block there. A liquid above the block or beside it (lava
                    flows) is looked for before the dig and again after it: before, the
                    block is not dug; after, the step fails before the body goes into the
                    opening. While the body stands at a dig or a placement, the moment
                    lava or fire comes to reach its box (it was not in it when the step
                    began), the dig is let go of and the step fails: the keys are chosen
                    again, the way out of it soonest
  a placement       ahead under the way (a bridge, below the body's feet): clicked at once,
                    while the keys go on as said above (the step cannot be made until the
                    block is there). At the feet's height or above (the block a step up goes
                    onto): the keys go up and the body, where its box reaches into that cell,
                    first goes to the middle of its own cell. Under the body: the keys go up,
                    the block is placed in a jump. No block is placed into a cell any box of
                    a player or a mob reaches (the game refuses it): the step fails with what
                    stands there. The step fails when no block is there afterwards
  A step that takes more than three times what it was expected to, and 1.5 s, has failed.
  A step that failed costs 20 s more each time it failed when the route is searched again,
  so another way is taken where there is one; the third failure of the same step ends the
  walk with the reason.

What is acted on only when seen applies here too: a block the body cannot see is not dug
(the step fails with "not in sight").
