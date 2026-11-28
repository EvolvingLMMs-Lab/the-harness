guide("nav-go"): walking the body to a goal, h.go and h.path.

The body is walked by one thing, its navigator. Code asks it for a walk and awaits what
came of it; nothing else presses the movement keys or turns the head for a walk.

await h.go(goal, options) -> report
  Walks the body to the goal, without a stop between the cells of the way, and resolves
  when the body is there or cannot get there. It never rejects for a way that failed: the
  report says so.
  It uses the channels move and look (guide("run-channels")): code that did not say it
  uses both gets an error. The hand (use) stays free for other code unless the way needs a
  dig or a placement; code that does not use the channel use walks ways without them.
  One walk at a time: a walk that begins ends the one before (its report: why "another
  walk began"). The walk is the code's: while the code is paused the keys are up and the
  walk waits; when the code ends the walk ends.

  goal, one of:
    {x, y, z, range}        the feet within `range` (default 0.5) of the point. Without y: of the
                            column at x, z, at any height (measured across). The route ends in
                            a cell the point is near; from there the body walks straight to the
                            point until it is within range.
    {block: [x, y, z], reach}
                            a cell from which the block is in sight and within `reach`
                            (default 4.25) of the eyes: where the body can dig, use or open it.
    {entity: id, range}     a cell from which the entity is in sight and within `range`
                            (default 3, what a hit reaches) of the eyes: where the body can
                            hit or use it. The same as for a block, so a walk that arrived
                            is followed by an act that does not fail for sight. The entity
                            may move: while it is in a straight walkable line from the body
                            that line's cells are the route (taken anew each tick, not
                            searched); else by a route,
                            searched again while the body walks on when it no longer ends at
                            the entity. The walk is over as soon as the body is at it.
    {entity: id, distance} or {away: [x, y, z], distance}
                            at least `distance` (default 10) from the entity or the point.
    'safe'                  the nearest cell that no hazard in force forbids.

  options (all optional):
    dig: false              no step that digs
    place: false            no step that places a block (a step places only a block that
                            is one whole cube, does not fall and does nothing when clicked:
                            never a bed, a slab, a stair, sand, gravel, a furnace, a
                            crafting table, a chest...). Any other block the body carries
                            may be placed: what is to be kept goes in keep.
    sprint: false           walking speed only
    drop: n                 the farthest the body lets itself fall in one step (default 3)
    keep: [names]           items this walk does not use: it digs with none of them and
                            places none of them (item names as in the inventory, e.g.
                            ['iron_pickaxe', 'obsidian']). The route is searched and timed
                            without them: a dig takes what the fastest item left takes, the
                            bare hand when none is left. A name that is no item is an error.

  report:
    arrived                 true: the body stands at the goal
    why                     when not arrived, one of: "no route: every way is closed or
                            forbidden (the rules in force)", "no route to the goal was
                            found in N s of searching from here" (N goes by how far the
                            goal is: 0.5 s and 0.25 s for each block, 8 s at most; where
                            the code of route rules took 0.05 s or more of the walk's
                            searches, it goes on "; of S s searched in all, T s were in
                            the code of NAME, ..."), "no
                            route: the body cannot stand at the goal without digging, and
                            this walk does not dig" (told at once: a goal {x, y, z, range}
                            where every cell has a block at the feet or the head, with
                            dig: false),
                            "the step to x, y, z failed 3 times: REASON", "the body cannot
                            come within R of the point: it stands D from it across" (a point
                            the body cannot stand that near, as one by a wall), "the entity is
                            gone", "stopped", "another walk began", "the code ended"
    steps                   cells walked
    dug, placed             blocks dug and placed on the way
    replans                 how often the route was searched (1: only at the start)
    dodged                  ticks in which the keys were other than straight ahead because
                            something was flying at the body
    pulled_back             times the server put the body back during the walk
    hit                     times the body lost health during the walk
    expected_seconds        what the first route was expected to take
    searched_seconds        what all the route searches of this walk took
    rule_seconds            {name: seconds}: how much of that was spent in the code of
                            each route rule in force (a rule is run for every step the
                            search looks at)
    seconds                 what the walk took
    at                      [x, y, z] where the body is

await h.path(goal, options) -> {found, why, steps, seconds, digs, places, cells, reached,
                                searched_seconds, rule_seconds}
  Searches the route h.go would take now and does not walk it: `seconds` is what it is
  expected to take, `digs` and `places` what it needs, `cells` its first 400 cells,
  `reached` the cell it ends at, `searched_seconds` and `rule_seconds` as in h.go's report.
  `found` false: `why` is "no route" (every way is closed: there is none), or "the search
  ran out of time (N s): the cells are the part of a route it found, as far as (x, y, z),
  not a route to the goal" (it says nothing about whether a route exists; `steps`,
  `seconds`, `digs`, `places`, `cells` and `reached` are then of that part), or "the search
  ran out of time (N s): it found no part of a route"; the rules' share follows as in h.go.
  A search asked for while the body is in the air waits until it stands.

Events the body notes (guide("run-events")): nav_route {why, goal} each time a route is
searched; nav_blocked {from, to, why, times} when a step failed; nav_rule {name, on} when a
hazard or route rule is put in force or taken out.

How a step's time is counted: guide("nav-cost"). How the body is kept out of harm on the
way: guide("nav-hazards"). What the navigator does at each tick: guide("nav-steps").
