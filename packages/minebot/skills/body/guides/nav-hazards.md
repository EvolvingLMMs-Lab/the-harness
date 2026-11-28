guide("nav-hazards"): hazards and route rules, the rules the body is walked by.

The navigator moves the body; what it keeps away from and which steps it may take is said
by rules that you define and switch on. None exists until you define one. A rule changes
the walk that runs: the route is searched again the moment a rule comes into force or goes
out of force. When a hazard's zones come to cover other cells, the route is searched again
only where the rest of it is now worse (a cell of it newly forbidden, or dearer); a zone that
changes off the route changes nothing.

Two kinds.
  A hazard reads the world and says where not to be and what is flying at the body.
  A route rule is asked about each step of a route and says whether it may be taken.

Defining (Python; kept on the body across programs and runs, like a sense).
  hazard(name, code)
    code: the body of a JavaScript function, not async, with these in scope:
      bot, Vec3     as in a sense: read only
      args          what avoid(name, args) gave
      moving(e)     [x, y, z], how the entity e really moved in the last tick, in blocks a
                    tick. (An entity's own velocity field keeps its last value when the
                    entity has stopped.)
    It returns {zones: [...], incoming: [...]}, either may be left out:
      a zone        {cells: [[x, y, z], ...]}, or {center: [x, y, z], radius}, or
                    {entity: id, radius} (it follows the entity), with one of
                      forbid: true    the body does not stand in it
                      seconds: n      standing in a cell of it adds n to the route's time
      incoming      {position: [x, y, z], velocity: [x, y, z] in blocks a tick, radius}:
                    something that flies. The body is kept out of where it will be, tick
                    by tick, for the next 12 ticks, by the keys alone: no route is searched
                    for it.
    It is read at every tick of a walk while it is in force. It has 5 ms: one that takes
    longer three times running is no longer read until it is defined again
    (walking_rules()["errors"] says so).
  route_rule(name, code)
    code: the body of a JavaScript function, not async, with step, bot, Vec3 and args in
    scope. step is {kind, from, to, block, tool}: kind one of walk, jump, drop, swim, dig,
    place; from and to the cells; for a dig, block is the block's name and tool the item it
    would be dug with (null: the bare hand).
    It returns false (the step is not taken) or a number, the seconds the step adds.
  drop_walking_rule(name)   removes one.
  walking_rules()           {"hazards", "rules", "active": [{"name", "kind", "args",
                            "owner"}], "errors"}.

Putting in force.
  From a program:    avoid(name, args=None) ... unavoid(name). In force until taken out.
  From code on the body:  h.avoid(name, args) ... h.unavoid(name). In force for as long as
                     that code lasts: when the code ends, however it ends, what it put in
                     force goes. await h.hold() waits until the code is told to stop.
  So a node of the tree keeps a rule in force for exactly as long as its situation lasts:
      set_reflex("near", when, lambda: run_js("h.avoid('NAME', args); await h.hold()"),
                 over=..., claims=[])
  claims=[] says the node's program uses no channel: it presses no key, so it takes the
  body from nothing, and the walk that runs goes on under the new rule. When `over` holds
  the program is ended and the rule goes with it.

What a forbidden zone does to a walk.
  - Ahead on the route: the route is searched again and goes round. The body walks on
    along the route it has while the new one is searched, unless the zone covers one of
    its next three steps: then it stops there until the new route is found.
  - Under the body: the cells of that zone are no longer forbidden to this walk but cost 10
    s each, so the new route leaves the zone by the shortest way and does not come back
    into it.
  - On every way to the goal: the walk ends, the body stays where it is, and the report
    says "no route: every way is closed or forbidden" with the rules in force.
  - h.go('safe') walks to the nearest cell outside every forbidden zone.

What does not go through here.
  A reaction that is not a matter of where the body stands (raising a shield, eating,
  putting out a fire, coming up for air) is an action of a node, as before. One that uses
  only the hand (claims=["use"]) runs beside a walk.
