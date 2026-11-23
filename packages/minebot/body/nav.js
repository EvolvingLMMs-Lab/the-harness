// Getting the body from where it is to a goal: the one thing that walks it.
//
// Two layers, both run at every physics tick while a walk lasts.
//   The route   a string of cells from where the body is to the goal, searched over the loaded
//               world (the search and the terrain rules are mineflayer-pathfinder's; its own
//               walking is not used). A step's cost is the seconds it is expected to take: the
//               distance at the speed of that way of moving, a block's dig time with the fastest
//               tool the body has, a placement's time. Blocks to place and tools to dig with are
//               counted against what the body has. On top of that come the rules that are in
//               force (hazards: cells not to stand in, or seconds they add; route rules: steps not
//               to take, or seconds they add). The route is searched again when it no longer
//               holds: the body is off it, a block on it changed, the rules or the inventory
//               changed, the goal moved.
//   Steering    which keys are down this tick. Each candidate set of keys is run through the
//               game's own physics for some ticks ahead, and the best is taken: how far it gets
//               along the route, whether it stays where a body can stand, and whether anything
//               flying meets the body on the way (each thing moved ahead by its own velocity, tick
//               for tick). So stepping aside from something that flies is a matter of this tick's
//               keys, not of a new route.
//
// Nothing here knows what is dangerous or what is worth keeping: hazards and route rules are
// code the caller defines and switches on.

const { Vec3 } = require('vec3')
const { performance } = require('perf_hooks')
const AStar = require('mineflayer-pathfinder/lib/astar')
const Movements = require('mineflayer-pathfinder/lib/movements')
const Move = require('mineflayer-pathfinder/lib/move')
const { PlayerState } = require('prismarine-physics')

// Blocks a second, as the game moves a player (walking, sprinting, in water), and what the
// other steps take; each is corrected by what the steps of that kind really took (see learn()).
const SPEED = { walk: 4.317, sprint: 5.612, swim: 2.2 }
const SECONDS = { jump: 0.25, place: 0.3, tool: 0.25, fall: (n) => Math.sqrt(2 * n / 32) }
const FORBID = 1e6
const HURT_SECOND = 10       // what a second of the body's box in lava or fire costs a route, in seconds of walking
// Blocks that do something when clicked (open a window, turn, ring, light): a walk never places them as a step or a
// bridge. They are things the body carries to use, and a later block put against one would click it instead.
const CLICKED = new Set(['furnace', 'blast_furnace', 'smoker', 'crafting_table', 'chest', 'trapped_chest', 'ender_chest', 'barrel',
  'dispenser', 'dropper', 'hopper', 'note_block', 'jukebox', 'loom', 'cartography_table', 'smithing_table', 'fletching_table',
  'lectern', 'bell', 'respawn_anchor', 'beehive', 'bee_nest', 'tnt', 'command_block', 'chain_command_block', 'repeating_command_block',
  'structure_block', 'jigsaw'])
// A block whose collision is one whole cube: what the route's search takes every placed block to be (a step to
// stand on, a wall, a bridge). A bed, slab, stair or fence is not: placed as one, the ground is not what the route was
// found for.
const fullCube = (b) => !!b && b.boundingBox === 'block' && Array.isArray(b.shapes) && b.shapes.length === 1 &&
  b.shapes[0].every((v, i) => v === (i < 3 ? 0 : 1))
const LEAVE = 10             // seconds a step costs inside a forbidden zone the body already stands in: the way out is the shortest
const AHEAD = 12             // ticks at least that a look ahead runs when something flies at the body
const AHEAD_MOST = 40        // ticks at most: a body that has not come to stand by then has not made it
const HELD = [3, 8]          // ticks a sidestep is kept in a look ahead before the route is followed again
const RESCUE_MS = 25         // of a tick the keys that bring a thrown body back onto the route may be looked for
const RUN = { sprint: true, jumpAt: null }   // the way followed after a sidestep when no planned way holds
const JUMP_WITHIN = 12       // ticks from now within which a jump is tried (a jump at a run is over in about that many)
const REST_MOST = 40         // ticks at most for a body with no key pressed to come to rest
const SEARCH_MS = 25         // of a tick a route search may take
// A search that is not through after this long gives the best part of a route it has (the way that gets
// nearest the goal): the body walks that, and the search goes on from its end. So the body stands for a search
// at most this long, however far or hard the goal is.
const SEARCH_PART_MS = 300
const SEARCH_TOTAL_MS = 8000 // then the search is given up, at the latest
const SEARCH_BASE_MS = 500   // a search is given up after this and SEARCH_BLOCK_MS for each block the goal is away:
const SEARCH_BLOCK_MS = 250  // a goal one block away after 0.75 s, ten away after 3 s, thirty and more after 8 s
// The search is greedy, as a person finds a way: it heads for the goal and looks aside only where it is stopped.
// Its guess of what is left is the straight way at a sprint times this, so what is nearer the goal is tried long
// before what is not. The route found is a good way, not the best one.
const GUESS = 4

module.exports = function makeNav (bot, { note }) {
  const registry = bot.registry
  // (The terrain rules ask the bot's pathfinder for the tool a block is dug with: ours.)
  bot.pathfinder = { bestHarvestTool: (block) => fastestTool(block).item }

  // ---------------------------------------------------------------- what was measured
  const measured = { walk: 1, dig: 1, place: 1 }   // real seconds / expected seconds, of late
  function learn (kind, expected, real) {
    if (!(expected > 0.05) || !(real > 0)) return
    measured[kind] = Math.min(4, Math.max(0.5, measured[kind] * 0.8 + (real / expected) * 0.2))
  }

  // ---------------------------------------------------------------- hazards and route rules
  //
  // A hazard is code that reads the world and returns {zones: [...], incoming: [...]}:
  //   a zone      {cells: [[x, y, z], ...]} or {center: [x, y, z] | entity: id, radius},
  //               with `forbid: true` (not to stand in) or `seconds` (what standing in it adds)
  //   incoming    {position: [x, y, z], velocity: [x, y, z] (blocks a tick), radius}: something
  //               that flies; the steering keeps the body out of its way
  // A route rule is code that gets one step of a route ({kind: walk|jump|drop|swim|dig|place,
  // from, to, block, tool, place}) and returns false (not to be taken) or the seconds it adds.
  const defined = { hazard: {}, rule: {} }     // name -> {fn, error, slow}
  const active = new Map()                     // name -> {kind, args, owner}
  let rulesVersion = 0
  let zones = []; let incoming = []; let zonesKey = ''
  // The zones change on their own (a cloud grows, a mob walks): that is counted apart from the rules, since a change
  // of zones makes a walk search again only where it makes the rest of its route worse.
  let zonesVersion = 0

  function define (kind, name, code) {
    const fn = kind === 'hazard' ? new Function('bot', 'Vec3', 'args', 'moving', code) : new Function('step', 'bot', 'Vec3', 'args', code)
    defined[kind][name] = { fn, error: null, slow: 0 }
    rulesVersion++
  }
  function undefine (kind, name) { delete defined[kind][name]; active.delete(name); rulesVersion++ }
  function avoid (name, args, owner) {
    const kind = defined.hazard[name] ? 'hazard' : defined.rule[name] ? 'rule' : null
    if (!kind) throw new Error(`no hazard or route rule is named ${name}: define it first`)
    active.set(name, { kind, args: args === undefined ? null : args, owner: owner || null })
    rulesVersion++
    note('nav_rule', { name, on: true, owner: owner || null })
  }
  function unavoid (name, owner) {
    const row = active.get(name)
    if (!row || (owner && row.owner !== owner)) return false
    active.delete(name); rulesVersion++
    note('nav_rule', { name, on: false })
    return true
  }
  function dropOwner (owner) { for (const [name, row] of [...active]) if (row.owner === owner) unavoid(name) }
  function listed () {
    return { hazards: Object.keys(defined.hazard), rules: Object.keys(defined.rule),
      active: [...active].map(([name, row]) => ({ name, kind: row.kind, args: row.args, owner: row.owner })),
      errors: Object.fromEntries(['hazard', 'rule'].flatMap(k => Object.entries(defined[k]).filter(([, d]) => d.error).map(([n, d]) => [n, d.error]))) }
  }

  function vec (p) { return Array.isArray(p) ? new Vec3(p[0], p[1], p[2]) : new Vec3(p.x, p.y, p.z) }
  // How every entity moved in the last tick, measured (what the game last said of a thing's velocity stays as it was
  // when the thing has stopped: an arrow in the ground still "flies"). moving(entity): [x, y, z] blocks a tick.
  const seen = new Map()
  let seenTick = -1; let ticked = 0
  bot.on('physicsTick', () => { ticked++ })
  function measure () {
    if (ticked === seenTick) return
    const ticks = Math.max(1, seenTick < 0 ? 1 : ticked - seenTick)
    seenTick = ticked
    for (const id in bot.entities) {
      const e = bot.entities[id]
      if (!e.position) continue
      const was = seen.get(id)
      // (Seen for the first time: what the game said of its velocity when it appeared, in blocks a tick.)
      seen.set(id, { pos: e.position.clone(), vel: was ? e.position.minus(was.pos).scaled(1 / ticks) : (e.velocity ? e.velocity.clone() : new Vec3(0, 0, 0)) })
    }
    for (const id of seen.keys()) if (!bot.entities[id]) seen.delete(id)
  }
  const moving = (entity) => { const row = entity && seen.get(String(entity.id)); return row ? [row.vel.x, row.vel.y, row.vel.z] : [0, 0, 0] }
  // Every tick: the zones and the flying things of the hazards in force, as they are now.
  function readHazards () {
    measure()
    const nextZones = []; const nextIncoming = []
    for (const [name, row] of active) {
      if (row.kind !== 'hazard') continue
      const d = defined.hazard[name]
      if (!d || d.slow >= 3) continue
      const began = performance.now()
      try {
        const out = d.fn(bot, Vec3, row.args, moving) || {}
        for (const z of out.zones || []) {
          const zone = { name, forbid: !!z.forbid, seconds: Number(z.seconds) || 0 }
          if (z.cells) zone.cells = new Set(z.cells.map(c => `${Math.floor(c[0])},${Math.floor(c[1])},${Math.floor(c[2])}`))
          else {
            const e = z.entity !== undefined ? bot.entities[z.entity] : null
            if (z.entity !== undefined && !e) continue
            zone.center = e ? e.position.clone() : vec(z.center)
            zone.radius = Number(z.radius) || 1
          }
          nextZones.push(zone)
        }
        for (const f of out.incoming || []) nextIncoming.push({ name, position: vec(f.position), velocity: vec(f.velocity), radius: Number(f.radius) || 0.5 })
        d.error = null
      } catch (error) { d.error = String(error && error.message).slice(0, 200) }
      d.slow = performance.now() - began > 5 ? d.slow + 1 : 0
      if (d.slow >= 3) d.error = 'it took more than 5 ms three times running: it is not read until it is defined again'
    }
    // (Zones are compared by the cells they cover, to the block: a zone that follows an entity
    // changes the route only when it comes to cover other cells.)
    const key = nextZones.map(z => z.name + (z.forbid ? '!' : z.seconds) + (z.cells ? [...z.cells].sort().join(';') : `${Math.floor(z.center.x)},${Math.floor(z.center.y)},${Math.floor(z.center.z)},${z.radius}`)).join('|')
    // A forbidden zone the body stands in cannot forbid its way out: its cells cost dearly instead, so the route
    // leaves it by the shortest way and does not come back.
    const at = bot.entity.position
    for (const zone of nextZones) zone.leaving = zone.forbid && inZone(zone, Math.floor(at.x), Math.floor(at.y + 0.001), Math.floor(at.z))
    zones = nextZones; incoming = nextIncoming
    if (key !== zonesKey) { zonesKey = key; zonesVersion++ }
  }
  function inZone (zone, x, y, z) {
    return zone.cells ? zone.cells.has(`${x},${y},${z}`)
      : (x + 0.5 - zone.center.x) ** 2 + (y + 0.5 - zone.center.y) ** 2 + (z + 0.5 - zone.center.z) ** 2 <= zone.radius ** 2
  }
  // What standing in a cell adds: FORBID, or seconds.
  function zoneCost (x, y, z) { return costIn(zones, x, y, z) }
  // The same, by the zones `zs` (those of an earlier tick).
  function costIn (zs, x, y, z) {
    let seconds = 0
    for (const zone of zs) {
      if (!inZone(zone, x, y, z)) continue
      if (zone.forbid && !zone.leaving) return FORBID
      seconds += zone.forbid ? LEAVE : zone.seconds
    }
    return seconds
  }
  // The search that computes now keeps the time: its own, and what each rule's code took of it.
  let timing = null
  const newClock = () => ({ ms: 0, rules: new Map() })
  const clockTold = (clock) => ({ searched_seconds: +(clock.ms / 1000).toFixed(2), rule_seconds: Object.fromEntries([...clock.rules].map(([name, ms]) => [name, +(ms / 1000).toFixed(2)])) })
  function ruleText (clock) {
    const rows = [...clock.rules].filter(([, ms]) => ms >= 50).sort((a, b) => b[1] - a[1])
    return rows.length ? `; of ${(clock.ms / 1000).toFixed(1)} s searched in all, ${rows.map(([name, ms]) => `${(ms / 1000).toFixed(1)} s were in the code of ${name}`).join(', ')}` : ''
  }
  function ruleCost (step) {
    let seconds = 0
    for (const [name, row] of active) {
      if (row.kind !== 'rule') continue
      const d = defined.rule[name]
      if (!d) continue
      const began = timing ? performance.now() : 0
      try {
        const out = d.fn(step, bot, Vec3, row.args)
        if (out === false) return FORBID
        seconds += Number(out) || 0
        d.error = null
      } catch (error) { d.error = String(error && error.message).slice(0, 200) } finally {
        if (timing) timing.rules.set(name, (timing.rules.get(name) || 0) + performance.now() - began)
      }
    }
    return seconds
  }

  // ---------------------------------------------------------------- tools and blocks
  const nbt = require('prismarine-nbt')
  function usesLeft (item) {
    const max = registry.items[item.type] && registry.items[item.type].maxDurability
    if (!max) return Infinity
    const damage = item.nbt ? (nbt.simplify(item.nbt).Damage || 0) : 0
    return max - damage
  }
  // The items a walk does not use (its option keep: [names]): it digs with none of them and places none of them.
  function keptOf (options) {
    const names = options && options.keep
    if (names === undefined || names === null) return null
    if (!Array.isArray(names) || names.some(name => typeof name !== 'string')) throw new Error('go(goal, {keep}): keep is a list of item names, the items the walk does not use')
    const unknown = names.filter(name => !registry.itemsByName[name])
    if (unknown.length) throw new Error(`go(goal, {keep}): no item is named ${unknown.join(', ')}`)
    return new Set(names)
  }
  // The item the block is dug fastest with, of what the body has and may still use (`spent`:
  // {slot: digs already planned with it}; `kept`: the names the walk does not use); {item: null} is the bare hand.
  function fastestTool (block, spent, kept) {
    const effects = bot.entity.effects
    const time = (item) => block.digTime(item ? item.type : null, false, false, false,
      item && item.nbt ? (nbt.simplify(item.nbt).Enchantments || []) : [], effects)
    let best = { item: null, ms: time(null) }
    for (const item of bot.inventory.items()) {
      if (!registry.items[item.type] || !registry.items[item.type].maxDurability) continue
      if (usesLeft(item) - ((spent && spent[item.slot]) || 0) <= 0) continue
      if (kept && kept.has(item.name)) continue
      const ms = time(item)
      if (ms < best.ms) best = { item, ms }
    }
    return best
  }

  // ---------------------------------------------------------------- the route's rules of terrain and time
  class Timed extends Movements {
    constructor (options) {
      super(bot)
      this.canDig = options.dig !== false
      this.kept = keptOf(options)
      this.allowSprinting = options.sprint !== false
      this.maxDropDown = options.drop === undefined ? 3 : options.drop
      this.infiniteLiquidDropdownDistance = false
      this.allow1by1towers = options.place !== false
      this.canOpenDoors = false
      this.allowEntityDetection = true
      // Blocks to place: every whole-cube block the body carries that falls to nothing (no sand or gravel) and does
      // nothing when clicked (no furnace, crafting table, chest...). Nothing that is not a whole cube (a bed, a slab).
      this.scafoldingBlocks = options.place === false ? [] : bot.inventory.items()
        .filter(item => !(this.kept && this.kept.has(item.name)) && !CLICKED.has(item.name))
        .filter(item => { const b = registry.blocksByName[item.name]; return fullCube(b) && !this.gravityBlocks.has(b.id) })
        .map(item => item.type).filter((type, i, all) => all.indexOf(type) === i)
      for (const name of ['lava', 'fire', 'soul_fire', 'sweet_berry_bush', 'wither_rose', 'campfire', 'soul_campfire', 'magma_block', 'cactus']) {
        if (registry.blocksByName[name]) this.blocksToAvoid.add(registry.blocksByName[name].id)
      }
      // What is forbidden is forbidden to the search itself, so that it finds the other way.
      this.exclusionAreasStep.push((b) => (b && b.position && zoneCost(b.position.x, b.position.y, b.position.z) >= FORBID) ? 100 : 0)
      this.exclusionAreasBreak.push((b) => (b && b.position && ruleCost({ kind: 'dig', to: b.position, block: b.name }) >= FORBID) ? 100 : 0)
      this.exclusionAreasPlace.push((b) => (b && b.position && ruleCost({ kind: 'place', to: b.position }) >= FORBID) ? 100 : 0)
      this.spent = options.spent || {}
      this.runups = new Map()
    }

    // A single snow layer is marked solid but has no collision shape: the server lets a body through it, and a block
    // used on it replaces it. So it is walked through, never placed against, and a block may be placed into its cell.
    getBlock (pos, dx, dy, dz) {
      const b = super.getBlock(pos, dx, dy, dz)
      if (b && b.name === 'snow' && b.shapes && b.shapes.length === 0) {
        b.safe = !this.blocksToAvoid.has(b.type)
        b.physical = false
        b.replaceable = true
      }
      return b
    }

    // A step's cost: the seconds it is expected to take.
    getNeighbors (node) {
      const out = []
      for (const move of super.getNeighbors(node)) {
        // A jump across a gap only where the body can take the run-up it needs (runupNeeded).
        if (move.parkour && runupNeeded(node, move, this.allowSprinting && bot.food > 6, this.runups) === null) continue
        const seconds = this.seconds(node, move)
        if (seconds >= FORBID) continue
        move.cost = seconds
        out.push(move)
      }
      return out
    }

    seconds (node, move) {
      const flat = Math.hypot(move.x - node.x, move.z - node.z)
      const dy = move.y - node.y
      const wet = this.getBlock(node, 0, 0, 0).liquid || this.getBlock(move, 0, 0, 0).liquid
      const kind = wet ? 'swim' : dy > 0 ? 'jump' : dy < 0 ? 'drop' : 'walk'
      const speed = wet ? SPEED.swim : this.allowSprinting && bot.food > 6 ? SPEED.sprint : SPEED.walk
      // A step up costs walking a block (a body that runs jumps up on its way); a drop, the longer of walking its
      // distance and falling (both go on at once). move.base: that, without its factor (what walking is learned on).
      let base = Math.max(flat, dy > 0 ? 1 : 0) / speed
      if (dy < 0 && !wet) base = Math.max(base, SECONDS.fall(-dy))
      move.base = base
      let seconds = base * measured.walk
      let rules = zoneCost(move.x, move.y, move.z)
      if (rules < FORBID) rules += ruleCost({ kind, from: node, to: move })
      // (The hand changes where the item a dig needs is not the one in it: the body's now, for the first dig.)
      let last = bot.heldItem ? bot.heldItem.slot : null
      for (const at of move.toBreak) {
        const block = bot.blockAt(at, false)
        if (!block) return FORBID
        const tool = fastestTool(block, this.spent, this.kept)
        seconds += (tool.ms / 1000) * measured.dig + (tool.item && tool.item.slot !== last ? SECONDS.tool : 0)
        if (tool.item) last = tool.item.slot
        if (rules < FORBID) rules += ruleCost({ kind: 'dig', from: node, to: at, block: block.name, tool: tool.item ? tool.item.name : null })
      }
      for (const p of move.toPlace) {
        if (p.useOne) continue
        seconds += SECONDS.place * measured.place + (p.jump ? SECONDS.jump : 0)
        if (rules < FORBID) rules += ruleCost({ kind: 'place', from: node, to: new Vec3(p.x + p.dx, p.y + p.dy, p.z + p.dz) })
      }
      // The digs and placements are done standing in the cell the step goes from: where the body's box there reaches
      // lava or fire, the time it stands there is time in what hurts, and costs as much more (a route that steps out
      // of it first is the cheaper).
      const standing = seconds - base * measured.walk
      if (standing > 0 && hurting(new Vec3(node.x + 0.5, node.y, node.z + 0.5))) seconds += standing * HURT_SECOND
      return rules >= FORBID ? FORBID : seconds + rules
    }
  }

  // ---------------------------------------------------------------- goals
  //
  // What a caller asks for, as data: {x, y, z, range} | {block: [x, y, z], reach} (a cell the
  // block is in sight and reach from) | {entity: id, range} | {away: [x, y, z] | entity: id,
  // distance} | 'safe' (the nearest cell no hazard forbids).
  const perBlock = GUESS / SPEED.sprint
  // Whether a body standing in the cell `n` is at `thing` (a Block or an Entity): from its eyes there the middle
  // of the thing is within `reach`, and the thing is in sight, by the test the body's acts go by (bot.inSight).
  // So where a walk says the body is at a thing, the body can act on it.
  function isAt (thing, n, reach) {
    const eye = new Vec3(n.x + 0.5, n.y + 1.62, n.z + 0.5)
    const middle = thing.shapes !== undefined ? thing.position.offset(0.5, 0.5, 0.5) : thing.position.offset(0, (thing.height || 1.8) / 2, 0)
    return eye.distanceTo(middle) <= reach && bot.inSight(thing, eye)
  }
  function makeGoal (spec) {
    if (spec === 'safe') return { text: 'safe', heuristic: () => 0, isEnd: (n) => zoneCost(n.x, n.y, n.z) < FORBID, moves: () => false }
    if (!spec || typeof spec !== 'object') throw new Error("go(goal): a goal is {x, y, z, range}, {block: [x, y, z]}, {entity: id, range}, {away, distance} or 'safe'")
    const flat = (n, p) => { const dx = Math.abs(n.x + 0.5 - p.x); const dz = Math.abs(n.z + 0.5 - p.z); return Math.max(dx, dz) + (Math.SQRT2 - 1) * Math.min(dx, dz) }
    if (spec.block) {
      const where = vec(spec.block).floored(); const reach = spec.reach || 4.25
      const centre = where.offset(0.5, 0.5, 0.5)
      // The block touches the two cells a body at `n` stands in (a side of its feet or head cell, under its feet,
      // over its head): standing there those two cells are open, so the block is in sight, whatever else on the
      // way is dug or not. (Sight as the world is now would never hold beside a block that is buried.)
      const touches = (n) => {
        const dx = Math.abs(where.x - n.x); const dz = Math.abs(where.z - n.z); const dy = where.y - n.y
        return (dx + dz === 1 && (dy === 0 || dy === 1)) || (dx + dz === 0 && (dy === -1 || dy === 2))
      }
      return { text: `in sight and reach of ${where}`,
        // What is left: to beside the block, in all three directions.
        heuristic: (n) => (Math.max(0, flat(n, centre) - 1) + Math.max(0, Math.abs(where.y - n.y - 0.5) - 1.5)) * perBlock,
        isEnd: (n) => {
          if (n.x === where.x && n.z === where.z && (n.y === where.y || n.y === where.y - 1)) return false   // (in the block's own cell)
          if (touches(n)) return true
          const block = bot.blockAt(where, false)
          return !block ? new Vec3(n.x + 0.5, n.y + 1.62, n.z + 0.5).distanceTo(centre) <= reach : isAt(block, n, reach)
        },
        moves: () => false }
    }
    if (spec.away !== undefined || (spec.entity !== undefined && spec.distance !== undefined)) {
      const where = () => spec.entity !== undefined ? (bot.entities[spec.entity] || {}).position : vec(spec.away)
      const distance = spec.distance || 10
      return { text: `at least ${distance} from it`,
        heuristic: (n) => { const p = where(); return p ? Math.max(0, distance - Math.hypot(n.x + 0.5 - p.x, n.z + 0.5 - p.z)) * perBlock : 0 },
        isEnd: (n) => { const p = where(); return !p || Math.hypot(n.x + 0.5 - p.x, n.y - p.y, n.z + 0.5 - p.z) >= distance },
        moves: () => spec.entity !== undefined }
    }
    if (spec.entity !== undefined) {
      // (3: what a hit reaches. The same as for a block: within range of the eyes, and in sight.)
      const range = spec.range === undefined ? 3 : spec.range
      return { text: `in sight and within ${range} of the entity`,
        heuristic: (n) => { const p = (bot.entities[spec.entity] || {}).position; return p ? Math.max(0, flat(n, p) - range) * perBlock : 0 },
        isEnd: (n) => { const e = bot.entities[spec.entity]; return !e || isAt(e, n, range) },
        gone: () => !bot.entities[spec.entity],
        where: () => (bot.entities[spec.entity] || {}).position,
        moves: () => true }
    }
    const p = new Vec3(Number(spec.x), Number(spec.y === undefined ? bot.entity.position.y : spec.y), Number(spec.z))
    if (!isFinite(p.x) || !isFinite(p.z)) throw new Error('go(goal): the goal has no x and z')
    const range = spec.range === undefined ? 0.5 : spec.range
    const anyY = spec.y === undefined
    return { text: `within ${range} of ${p.floored()}`, point: p, range,
      // Whether the body is at the goal: its feet within `range` of the point (across only, for a goal with no height).
      at: (pos) => (anyY ? Math.hypot(pos.x - p.x, pos.z - p.z) : Math.hypot(pos.x - p.x, pos.y - p.y, pos.z - p.z)) <= range,
      // (What is left is the distance across, and the height to the goal past its first block: a block up or down on
      // the way costs about what walking it does, but ten blocks below the goal are ten blocks from it.)
      heuristic: (n) => (Math.max(0, flat(n, p) - range) + (anyY ? 0 : Math.max(0, Math.abs(n.y - Math.floor(p.y)) - 1 - range))) * perBlock,
      isEnd: (n) => anyY ? Math.hypot(n.x + 0.5 - p.x, n.z + 0.5 - p.z) <= Math.max(range, 0.71) : Math.hypot(n.x + 0.5 - p.x, n.y - p.y, n.z + 0.5 - p.z) <= Math.max(range, 0.71),
      // The cells that are at the goal, where they are few enough to list (a goal with a height, of a small range).
      cells: () => {
        const r = Math.max(range, 0.71)
        if (anyY || r > 3) return null
        const out = []
        for (let x = Math.floor(p.x - r - 1); x <= Math.floor(p.x + r + 1); x++) {
          for (let y = Math.floor(p.y - r - 1); y <= Math.floor(p.y + r + 1); y++) {
            for (let z = Math.floor(p.z - r - 1); z <= Math.floor(p.z + r + 1); z++) {
              if (Math.hypot(x + 0.5 - p.x, y - p.y, z + 0.5 - p.z) <= r) out.push(new Vec3(x, y, z))
            }
          }
        }
        return out
      },
      moves: () => false }
  }
  // A goal no search can reach: every cell at it has a block where the body's feet or head would be, and the walk
  // may not dig. Told at once, with no search. null: the goal may be reached, or that is not known (a cell not loaded).
  function shut (goal, options) {
    if (!options || options.dig !== false || !goal.cells) return null
    const cells = goal.cells()
    if (!cells || !cells.length) return null
    const full = fullCube
    for (const c of cells) {
      const feet = bot.blockAt(c, false); const head = bot.blockAt(c.offset(0, 1, 0), false)
      if (!feet || !head) return null
      if (head.boundingBox !== 'block' && !full(feet)) return null
    }
    return 'no route: the body cannot stand at the goal without digging, and this walk does not dig'
  }

  // ---------------------------------------------------------------- searching a route
  function startCell () {
    const at = bot.entity.position
    const p = at.floored()
    const under = bot.blockAt(p, false)
    // (Standing on a block that is not a full block high, the body is in the cell above it.)
    const up = under && under.boundingBox === 'block' && at.y - p.y > 0.001 && bot.entity.onGround ? 1 : 0
    const cell = new Vec3(p.x, p.y + up, p.z)
    // The cell of the body's middle is where it stands only when there is ground under it. A body on the ground
    // with nothing under its middle stands on the edge of a block beside: its box (0.6 across) reaches over that
    // block. Then it stands in that block's cell, the nearest such to its middle: every step from there (a bridge,
    // a block under the feet) is placed against ground that is there.
    if (!bot.entity.onGround) return cell
    const solid = (b) => !!b && b.boundingBox === 'block'
    if (solid(bot.blockAt(cell.offset(0, -1, 0), false))) return cell
    let best = null
    for (let x = Math.floor(at.x - 0.3); x <= Math.floor(at.x + 0.3); x++) {
      for (let z = Math.floor(at.z - 0.3); z <= Math.floor(at.z + 0.3); z++) {
        if (x === cell.x && z === cell.z) continue
        const c = new Vec3(x, cell.y, z)
        if (!solid(bot.blockAt(c.offset(0, -1, 0), false)) || solid(bot.blockAt(c, false)) || solid(bot.blockAt(c.offset(0, 1, 0), false))) continue
        const d = Math.hypot(x + 0.5 - at.x, z + 0.5 - at.z)
        if (!best || d < best.d) best = { c, d }
      }
    }
    return best ? best.c : cell
  }
  // A body in the air (it jumps or falls: not on the ground, not in a liquid, not on something it climbs, and moving
  // up or down) stands in no cell yet. A route starts from the cell the body stands in, so none is searched till it does.
  const CLIMBED = /^(ladder|vine|scaffolding|weeping_vines|twisting_vines)/
  function stands () {
    const e = bot.entity
    if (e.onGround || e.isInWater || e.isInLava || e.velocity.y === 0) return true
    const b = bot.blockAt(e.position, false)
    return !!b && CLIMBED.test(b.name)
  }
  function makeSearch (goal, options, penalties, clock) {
    const movements = new Timed(options)
    // A step that failed is paid for when it is planned again.
    const base = movements.seconds.bind(movements)
    movements.seconds = (node, move) => base(node, move) + (penalties.get(`${node.x},${node.y},${node.z}>${move.hash}`) || 0)
    movements.clearCollisionIndex(); movements.updateCollisionIndex()
    const at = startCell()
    const start = new Move(at.x, at.y, at.z, movements.countScaffoldingItems(), 0)
    // The search is given up the sooner the nearer the goal is. (A goal that names no distance, 'safe', has the longest.)
    const blocks = goal.heuristic(start) / perBlock
    const bound = blocks > 0 ? Math.min(SEARCH_TOTAL_MS, SEARCH_BASE_MS + SEARCH_BLOCK_MS * blocks) : SEARCH_TOTAL_MS
    const search = new AStar(start, movements, goal, bound, SEARCH_MS, -1)
    const compute = search.compute.bind(search)
    search.compute = () => {
      const began = performance.now(); timing = clock
      try { return compute() } finally { timing = null; clock.ms += performance.now() - began }
    }
    return { search, movements, bound }
  }
  // What a found route needs, counted: the digs by tool against what the tools still do.
  function count (path) {
    const out = { steps: path.length, seconds: 0, digs: 0, places: 0 }
    for (const move of path) { out.seconds += move.cost; out.digs += move.toBreak.length; out.places += move.toPlace.filter(p => !p.useOne).length }
    out.seconds = +out.seconds.toFixed(1)
    return out
  }
  // The tools the route's digs would use up: {slot: digs} of those it asks more of than they have.
  function overspent (path, kept) {
    const spent = {}; const over = {}
    for (const move of path) {
      for (const at of move.toBreak) {
        const block = bot.blockAt(at, false)
        if (!block) continue
        const tool = fastestTool(block, over, kept).item
        if (!tool) continue
        spent[tool.slot] = (spent[tool.slot] || 0) + 1
        if (spent[tool.slot] > usesLeft(tool)) over[tool.slot] = Infinity
      }
    }
    return over
  }

  // h.path: a route searched and not walked.
  async function path (spec, options = {}, alive = () => true) {
    const goal = makeGoal(spec)
    keptOf(options)
    readHazards()
    const closed = shut(goal, options)
    const clock = newClock()
    if (closed) return { found: false, why: closed, ...count([]), cells: [], reached: null, ...clockTold(clock) }
    while (!stands() && alive()) await new Promise(resolve => bot.once('physicsTick', resolve))
    let spent = {}
    for (let attempt = 0; attempt < 3; attempt++) {
      const { search, bound } = makeSearch(goal, { ...options, spent }, new Map(), clock)
      let result = search.compute()
      while (result.status === 'partial' && alive()) { await new Promise(resolve => setImmediate(resolve)); result = search.compute() }
      const over = overspent(result.path, keptOf(options))
      if (Object.keys(over).length && attempt < 2) { spent = { ...spent, ...over }; continue }
      // (A search that ran out of time has the part of a route that got nearest the goal: said, with where it ends.)
      const end = result.path[result.path.length - 1]
      const reached = end ? [end.x, end.y, end.z] : null
      const why = result.status === 'success' ? null : result.status === 'noPath' ? 'no route'
        : `the search ran out of time (${+(bound / 1000).toFixed(1)} s): ${reached ? `the cells are the part of a route it found, as far as (${reached.join(', ')}), not a route to the goal` : 'it found no part of a route'}${ruleText(clock)}`
      return { found: result.status === 'success', why, ...count(result.path),
        cells: result.path.slice(0, 400).map(m => [m.x, m.y, m.z]), reached, ...clockTold(clock) }
    }
  }

  // ---------------------------------------------------------------- steering
  const KEYS = ['forward', 'back', 'left', 'right', 'jump', 'sprint', 'sneak']
  // What the body can press in place of what the route asks for, to be out of the way of something that flies.
  const SIDESTEPS = []
  for (const f of [1, 0, -1]) for (const s of [0, -1, 1]) for (const jump of [false, true]) {
    SIDESTEPS.push({ forward: f === 1, back: f === -1, left: s === -1, right: s === 1, jump, sprint: f === 1, sneak: false })
  }
  const HURTS = /lava|fire|sweet_berry|wither_rose/
  // Whether the box of a body at `pos` (0.6 across, 1.8 high) reaches a cell that holds what hurts (lava of any
  // level, fire...: what the box touches burns it, the cell beside included): 1 if it does, 0 if not. Summed over the
  // ticks of a way, it is how long the way keeps the body in what hurts (its exposure).
  function hurting (pos) {
    const y = Math.floor(pos.y + 0.001)
    for (let cx = Math.floor(pos.x - 0.299); cx <= Math.floor(pos.x + 0.299); cx++) {
      for (let cz = Math.floor(pos.z - 0.299); cz <= Math.floor(pos.z + 0.299); cz++) {
        for (let cy = y; cy <= Math.floor(pos.y + 1.799); cy++) {
          const b = bot.blockAt(new Vec3(cx, cy, cz), false)
          if (b && HURTS.test(b.name)) return 1
        }
      }
    }
    return 0
  }
  // Whether the cell of a body at `pos` is not forbidden.
  function allowed (pos) { return zoneCost(Math.floor(pos.x), Math.floor(pos.y + 0.001), Math.floor(pos.z)) < FORBID }
  // A place for the body to be at, with nothing that hurts in reach of its box.
  function standable (pos) { return allowed(pos) && !hurting(pos) }

  // ---- The run-up of a jump across a gap (a parkour step: `move` is 2 to 4 cells from `from`, straight along x or z).
  // How far a body jumps depends on how fast it runs at the take-off, so the route only holds a jump the body can make
  // with a run-up it can take: from at rest at the middle of the cell k cells behind the take-off cell (k = 0: the
  // take-off cell itself), forward at a run (or a walk), up into a jump at the last ticks before it leaves the take-off
  // cell, forward let go of over the landing cell: it lands on the landing cell. By the game's own physics, in the world
  // as it is. Returns the fewest such k (0 to RUNUP_MOST) whose cells behind the take-off are cells to walk on, or null
  // where none is (the jump is not one the body can make there). A body that comes to the take-off already at speed
  // along the jump needs none of it; one that does not takes that run-up first.
  const RUNUP_MOST = 3
  function runupNeeded (from, move, sprint, cache) {
    const dx = Math.sign(move.x - from.x); const dz = Math.sign(move.z - from.z)
    if ((dx !== 0) === (dz !== 0)) return null
    const key = `${from.x},${from.y},${from.z}>${move.x},${move.y},${move.z}|${sprint}`
    if (cache && cache.has(key)) return cache.get(key)
    // (A take-off on a block the route is still to place is not there to be judged by physics yet: the jump is taken
    // as its cells allow it, and judged when the body stands there.)
    const under = bot.blockAt(new Vec3(from.x, from.y - 1, from.z), false)
    if (!under || under.boundingBox !== 'block') return 0
    let need = null
    for (let k = 0; k <= RUNUP_MOST && need === null; k++) {
      if (k > 0 && !runCell(new Vec3(from.x - dx * k, from.y, from.z - dz * k), new Vec3(from.x - dx * (k - 1), from.y, from.z - dz * (k - 1)))) break
      if (jumpsFrom(from, move, dx, dz, k, sprint)) need = k
    }
    if (cache) cache.set(key, need)
    return need
  }
  // A cell of a run-up: floor under it, room for the body, nothing that hurts, no rule against stepping there.
  function runCell (c, next) {
    const floor = bot.blockAt(c.offset(0, -1, 0), false); const feet = bot.blockAt(c, false); const head = bot.blockAt(c.offset(0, 1, 0), false)
    if (!floor || floor.boundingBox !== 'block' || !feet || feet.boundingBox !== 'empty' || !head || head.boundingBox !== 'empty') return false
    if (!standable(new Vec3(c.x + 0.5, c.y, c.z + 0.5))) return false
    return ruleCost({ kind: 'walk', from: next, to: c }) < FORBID && ruleCost({ kind: 'walk', from: c, to: next }) < FORBID
  }
  function jumpsFrom (from, move, dx, dz, k, sprint) {
    const yaw = Math.atan2(-dx, -dz)
    const start = () => {
      const s = new PlayerState(bot, {})
      s.pos = new Vec3(from.x + 0.5 - dx * k, from.y, from.z + 0.5 - dz * k); s.vel = new Vec3(0, 0, 0)
      s.onGround = true; s.isInWater = false; s.isInLava = false; s.isInWeb = false; s.isCollidedHorizontally = false; s.isCollidedVertically = true
      s.jumpTicks = 0; s.jumpQueued = false; s.yaw = yaw; s.pitch = 0
      return s
    }
    const over = (p) => Math.floor(p.x) === move.x && Math.floor(p.z) === move.z
    const step = (s, keys) => { s.control = { forward: !!keys.forward, back: false, left: false, right: false, jump: !!keys.jump, sprint: !!keys.sprint, sneak: false }; s.yaw = yaw; bot.physics.simulatePlayer(s, bot.world) }
    // The tick at which a run with no jump has gone past the far edge of the take-off cell: the jump comes at the tick
    // before it or at the two before that (a jump at the edge itself is the longest).
    let leave = null
    const s0 = start()
    for (let t = 0; t < 20 * (k + 2); t++) {
      step(s0, { forward: true, sprint })
      if ((s0.pos.x - (from.x + 0.5)) * dx + (s0.pos.z - (from.z + 0.5)) * dz > 0.5) { leave = t; break }
    }
    if (leave === null) return false
    for (const jumpAt of [leave - 1, leave - 2, leave - 3]) {
      if (jumpAt < 0) continue
      const s = start(); let up = false
      for (let t = 0; t < jumpAt + AHEAD_MOST; t++) {
        step(s, { forward: !(up && over(s.pos)), sprint, jump: t === jumpAt })
        if (t === jumpAt) up = true
        if (hurting(s.pos)) break
        if (s.pos.y < Math.min(from.y, move.y) - 1.5) break
        if (up && t > jumpAt && s.onGround) { if (over(s.pos) && Math.abs(s.pos.y - move.y) < 0.6) return true; break }
      }
    }
    return false
  }

  // What stands in the cell `c` so that no block can be placed there: the game refuses a block whose cell any box of a
  // player or a mob (or a boat, a minecart) reaches, the body's own included. Dropped items, arrows and the like do
  // not count. Returns that entity, or null.
  // The entities the game lets no block be placed into (its blocksBuilding: every living thing, an end crystal, a
  // falling block, lit TNT, a boat, a minecart). An item, an arrow, an orb, a breath cloud or a fireball does not
  // stop a placement. (The game data calls every entity a "mob": the kind is told by its category, and the 1.16 mobs
  // the data has no category for, and the one non-living thing among the hostile ones, by name.)
  const LIVING = new Set(['Hostile mobs', 'Passive mobs'])
  const blocksBuilding = (e) => e === bot.entity || e.type === 'player' ||
    (LIVING.has(e.kind) && e.name !== 'evoker_fangs') ||
    /^(player|armor_stand|bee|fox|hoglin|piglin|strider|zoglin|zombified_piglin|end_crystal|falling_block|tnt|boat)$|minecart/.test(e.name || '')
  function occupant (c) {
    for (const e of Object.values(bot.entities)) {
      if (!e || !e.position || !blocksBuilding(e)) continue
      const w = (e.width || 0.6) / 2; const h = e.height || 1.8; const p = e.position
      if (p.x + w > c.x + 1e-6 && p.x - w < c.x + 1 - 1e-6 && p.z + w > c.z + 1e-6 && p.z - w < c.z + 1 - 1e-6 &&
          p.y + h > c.y + 1e-6 && p.y < c.y + 1 - 1e-6) return e
    }
    return null
  }

  // ---------------------------------------------------------------- walking a route
  let walk = null              // the walk that has the legs: one at a time
  function release () { for (const key of KEYS) bot.setControlState(key, false) }

  // h.go: walk to the goal. Resolves with {arrived, why, ...} when the body is there or cannot get there.
  function go (spec, options = {}, ctl) {
    keptOf(options)
    if (walk) walk.finish({ arrived: false, why: 'another walk began' })
    const goal = makeGoal(spec)
    const began = Date.now()
    const closed = shut(goal, options)
    if (closed) {
      const p = bot.entity.position
      const told = { arrived: false, why: closed, steps: 0, dug: 0, placed: 0, replans: 0, dodged: 0, rescued: 0, pulled_back: 0, hit: 0, expected_seconds: null, ...clockTold(newClock()), seconds: 0, at: [+p.x.toFixed(2), +p.y.toFixed(2), +p.z.toFixed(2)] }
      return { done: Promise.resolve(told), stop: () => {} }
    }
    const report = { arrived: false, why: null, steps: 0, dug: 0, placed: 0, replans: 0, dodged: 0, rescued: 0, pulled_back: 0, hit: 0, expected_seconds: null }
    let resolve
    const done = new Promise(r => { resolve = r })
    const penalties = new Map(); const failures = new Map()
    const clock = newClock()          // (of all the searches of this walk)
    const me = {
      goal, options, route: null, index: 0, searching: null, busy: false, version: -1, inventory: null, stepBegan: 0, stepFrom: null,
      health: bot.health, why: 'the walk began', over: false, nearest: Infinity,
      finish (extra) {
        if (me.over) return
        me.over = true
        if (walk === me) walk = null
        bot.removeListener('physicsTick', tick); bot.removeListener('forcedMove', pulled); bot.removeListener('entityHurt', hurt)
        bot.removeListener('death', died)
        release()
        const at = bot.entity.position
        resolve({ ...report, ...extra, ...clockTold(clock), seconds: +((Date.now() - began) / 1000).toFixed(1), at: [+at.x.toFixed(2), +at.y.toFixed(2), +at.z.toFixed(2)] })
      }
    }
    walk = me
    // The means the body has for a route: the kinds of tool it has, and whether it has a block to place. An item being
    // moved (from slot to slot, to the hand) is on the cursor meanwhile, not in a slot: it is counted there, so a move
    // changes nothing. (How many blocks are left changes with every placement; a route that asks for more than there
    // are fails at that step and is searched again.)
    const inventoryKey = () => {
      const items = bot.inventory.items()
      if (bot.inventory.selectedItem) items.push(bot.inventory.selectedItem)
      const tools = new Set(items.filter(i => registry.items[i.type] && registry.items[i.type].maxDurability).map(i => i.type))
      const blocks = items.some(i => { const b = registry.blocksByName[i.name]; return b && b.boundingBox === 'block' })
      return { tools, blocks }
    }
    // The route no longer holds by the means it was searched with only when a means its remaining steps use is gone:
    // a kind of tool, where steps are still to dig; the last block, where blocks are still to be placed. More items,
    // or the same ones elsewhere, change nothing.
    const meansGone = (had, now, rest) => !!had && (
      (had.blocks && !now.blocks && rest.some(m => m.toPlace.some(p => !p.useOne))) ||
      ([...had.tools].some(t => !now.tools.has(t)) && rest.some(m => m.toBreak.length)))
    const replan = (why) => { me.route = null; me.searching = null; me.next = null; me.worse = false; me.why = why }
    const pulled = () => { report.pulled_back++; replan('the server put the body back') }
    const died = () => me.finish({ arrived: false, why: 'the body died' })
    const hurt = (entity) => { if (entity === bot.entity) { if (bot.health < me.health) report.hit++; me.health = bot.health } }
    const fail = (from, move, why) => {
      const key = `${from.x},${from.y},${from.z}>${move.hash}`
      const n = (failures.get(key) || 0) + 1
      failures.set(key, n); penalties.set(key, n * 20)
      const at = bot.entity.position
      const under = bot.blockAt(at.offset(0, -0.2, 0), false)
      note('nav_blocked', { from: [from.x, from.y, from.z], to: [move.x, move.y, move.z], why, times: n, parkour: !!move.parkour,
        at: [+at.x.toFixed(2), +at.y.toFixed(2), +at.z.toFixed(2)], on: under ? under.name : null, ground: bot.entity.onGround, water: !!bot.entity.isInWater })
      if (n >= 3) return me.finish({ arrived: false, why: `the step to ${move.x}, ${move.y}, ${move.z} failed ${n} times: ${why}` })
      replan(`a step failed: ${why}`)
    }

    // A block goes into `target` only when no box is in it: said as what stands there, not left to the game to refuse.
    function clearOf (target) {
      const e = occupant(target)
      if (!e) return
      const where = `(${target.x}, ${target.y}, ${target.z})`
      const b = bot.entity.position
      throw new Error(e === bot.entity ? `the body's own box is in ${where}, where the block goes (the body at ${b.x.toFixed(2)}, ${b.y.toFixed(2)}, ${b.z.toFixed(2)})` : `a ${e.name || e.type} stands in ${where}, where the block goes`)
    }
    // The body to the middle of `cell`, at a sneak (it keeps to the edge of what it stands on), and to rest there.
    async function centre (cell) {
      const m = middle(cell)
      for (let k = 0; k < 20; k++) {
        const p = bot.entity.position
        if (Math.hypot(m.x - p.x, m.z - p.z) < 0.1) break
        await bot.look(Math.atan2(-(m.x - p.x), -(m.z - p.z)), 0, true)
        bot.setControlState('sneak', true); bot.setControlState('forward', true)
        await bot.waitForTicks(1)
      }
      release()
      for (let k = 0; k < 10 && Math.hypot(bot.entity.velocity.x, bot.entity.velocity.z) > 0.003; k++) await bot.waitForTicks(1)
    }

    // A liquid above the cell `at` or beside it (lava flows, and may have come since the route was searched): what is
    // dug there opens the way to it.
    function liquidBeside (at) {
      for (const [dx, dy, dz] of [[0, 1, 0], [1, 0, 0], [-1, 0, 0], [0, 0, 1], [0, 0, -1]]) {
        const near = bot.blockAt(at.offset(dx, dy, dz), false)
        if (near && (near.name === 'lava' || near.name === 'water' || (near.getProperties && near.getProperties().waterlogged === true))) return near
      }
      return null
    }
    async function work (from, move) {
      // The digs and placements of a step, with the keys up: each checked by what the game then has there. The body
      // stands meanwhile, and what hurts may come to it (lava flows in, a fireball lights the floor): the moment its
      // box reaches a cell of it, the dig in hand is let go of and the step fails, so that the keys are chosen again,
      // by the exposure of each way (choose): the way out of it soonest.
      me.busy = true
      release()
      // (The route this step is of was chosen with the body where it is: already in what hurts, that was known, and the
      // step is the way on from it. What changes the step is what hurts coming to the body while it stands.)
      let hurt = null; const known = hurting(bot.entity.position)
      const watch = () => {
        if (hurt || known || !hurting(bot.entity.position)) return
        const p = bot.entity.position
        hurt = `what hurts reached the body as it stood at (${p.x.toFixed(2)}, ${p.y.toFixed(2)}, ${p.z.toFixed(2)})`
        if (bot.targetDigBlock) bot.stopDigging()
      }
      const unhurt = () => { if (hurt) throw new Error(hurt) }
      bot.on('physicsTick', watch)
      try {
        watch(); unhurt()
        for (const at of move.toBreak.slice()) {
          const block = bot.blockAt(at, false)
          if (!block || block.boundingBox === 'empty') continue
          // What the search judged by, judged again before the block is dug and after (the world goes on meanwhile):
          // a liquid there now would flow into the way.
          const wet = liquidBeside(at)
          if (wet) throw new Error(`${wet.name} beside ${block.name} at (${at.x}, ${at.y}, ${at.z}) would flow in: not dug`)
          const tool = fastestTool(block, null, me.movements.kept)
          // The hand is changed only where it has to be: for an item that digs the block faster, and to put away
          // an item this walk does not use. Where no item is faster, the block is dug with what the hand holds.
          const kept = me.movements.kept
          if (tool.item && (!bot.heldItem || bot.heldItem.slot !== tool.item.slot)) await bot.equip(tool.item, 'hand')
          else if (!tool.item && bot.heldItem && kept && kept.has(bot.heldItem.name)) await bot.unequip('hand')
          const t0 = Date.now()
          let out
          try { out = await bot.dig(block, true) } catch (error) { unhurt(); throw error }
          unhurt()
          learn('dig', tool.ms / 1000, (Date.now() - t0) / 1000)
          if (!out.gone) throw new Error(`${block.name} was not dug`)
          report.dug++
          const came = liquidBeside(at)
          if (came) throw new Error(`${came.name} came beside (${at.x}, ${at.y}, ${at.z}) while it was dug: the way is open to it`)
        }
        for (const p of move.toPlace.slice()) {
          if (p.useOne) continue
          const target = new Vec3(p.x + p.dx, p.y + p.dy, p.z + p.dz)
          const there = bot.blockAt(target, false)
          if (there && there.boundingBox === 'block') continue
          const item = bot.inventory.items().find(i => me.movements.scafoldingBlocks.includes(i.type))
          if (!item) throw new Error('no block left to place')
          if (!bot.heldItem || bot.heldItem.type !== item.type) await bot.equip(item, 'hand')
          const t0 = Date.now()
          if (p.jump) {
            // Under the body: jump, and place when the feet are clear of the cell.
            bot.setControlState('jump', true)
            for (let k = 0; k < 14 && bot.entity.position.y < target.y + 1.0; k++) await bot.waitForTicks(1)
            bot.setControlState('jump', false)
            if (bot.entity.position.y < target.y + 1.0) throw new Error('the jump did not clear the cell to place into')
          }
          // The cell has to be free of every box first, the body's own too: the body that reaches into the cell beside
          // it goes to the middle of its own cell (there its box keeps out of every cell beside it).
          if (occupant(target) === bot.entity && !p.jump) await centre(from)
          unhurt()
          clearOf(target)
          const against = bot.blockAt(new Vec3(p.x, p.y, p.z), false)
          if (!against || against.boundingBox !== 'block') throw new Error('nothing to place against')
          const out = await bot.placeBlock(against, new Vec3(p.dx, p.dy, p.dz))
          learn('place', SECONDS.place, (Date.now() - t0) / 1000)
          unhurt()
          if (!out.placed) throw new Error('the block was not placed')
          report.placed++
        }
        move.toBreak.length = 0; move.toPlace.length = 0
      } catch (error) {
        if (!me.over) fail(from, move, String(error && error.message).slice(0, 160))
      } finally { bot.removeListener('physicsTick', watch); me.busy = false; me.stepBegan = Date.now() }
    }

    // Place the blocks of a step while the body walks on: nothing waits for it but the step's own arrival.
    async function placeAhead (from, move) {
      me.placing = true
      try {
        for (const p of move.toPlace.slice()) {
          const target = new Vec3(p.x + p.dx, p.y + p.dy, p.z + p.dz)
          const there = bot.blockAt(target, false)
          if (there && there.boundingBox === 'block') continue
          const item = bot.inventory.items().find(i => me.movements.scafoldingBlocks.includes(i.type))
          if (!item) throw new Error('no block left to place')
          if (!bot.heldItem || bot.heldItem.type !== item.type) await bot.equip(item, 'hand')
          // (The body walks on meanwhile: a box of its own in the cell is waited out for a few ticks.)
          for (let k = 0; k < 6 && occupant(target) === bot.entity; k++) await bot.waitForTicks(1)
          clearOf(target)
          const against = bot.blockAt(new Vec3(p.x, p.y, p.z), false)
          if (!against || against.boundingBox !== 'block') throw new Error('nothing to place against')
          const out = await bot.placeBlock(against, new Vec3(p.dx, p.dy, p.dz))
          if (!out.placed) throw new Error('the block was not placed')
          report.placed++
        }
        move.toPlace.length = 0
      } catch (error) {
        if (!me.over && me.route && me.route.includes(move)) fail(from, move, String(error && error.message).slice(0, 160))
      } finally { me.placing = false }
    }

    function tick () {
      if (me.over || me.busy) return
      if (ctl && ctl.stopped()) return me.finish({ arrived: false, why: 'stopped' })
      if (ctl && ctl.paused()) { release(); return }
      if (goal.gone && goal.gone()) return me.finish({ arrived: false, why: 'the entity is gone' })
      readHazards()
      const here = startCell()
      if (goal.where) {
        // A goal that moves. The walk is over as soon as the body is at it (in sight and within range, as the
        // goal says). And while it is in a straight walkable line from the body, that line is the route: its cells,
        // from the body to where the goal is now, taken anew each tick and not searched. The keys along it are
        // chosen as along any route.
        const to = goal.where(); const pos = bot.entity.position
        const grounded = bot.entity.onGround || !!bot.entity.isInWater
        if (to && grounded && goal.isEnd(here)) return me.finish({ arrived: true })
        if (to && grounded && Math.abs(to.y - pos.y) < 0.6 && Math.hypot(to.x - pos.x, to.z - pos.z) <= 24 && lineWalkable(pos, new Vec3(to.x, pos.y, to.z))) {
          me.searching = null; me.next = null; me.why = 'the goal is no longer straight ahead'
          me.route = lineCells(here, pos, to); me.stepFrom = here; me.complete = true; me.line = true; me.stepBegan = Date.now()
          me.index = me.route.length ? progress(pos, grounded, 0) : 0
          if (me.index >= me.route.length) { release(); return }
        } else if (me.line) { me.line = false; me.route = null }
      }
      // The route no longer holds?
      const inv = inventoryKey()
      if (me.route && !me.line) {
        // The zones changed: the rest of the route is weighed by the zones as they are and as they were when it was
        // last weighed. Only where it is now worse is a better one looked for; a change elsewhere (a cloud growing far
        // off) changes nothing. Where a zone forbids one of the next steps the body stops and searches; else it walks
        // on along the route it has while the new one is searched.
        if (me.zonesSeen !== zonesVersion) {
          const before = me.zonesAt; me.zonesSeen = zonesVersion; me.zonesAt = zones
          const rest = me.route.slice(me.index)
          const sum = (zs) => rest.reduce((s, m) => s + Math.min(costIn(zs, m.x, m.y, m.z), FORBID), 0)
          if (before && sum(zones) > sum(before) + 0.01) {
            if (rest.slice(0, 3).some(m => zoneCost(m.x, m.y, m.z) >= FORBID)) replan('a zone came onto the next steps')
            else me.worse = true
          }
        }
      }
      if (me.route && !me.line) {
        if (me.version !== rulesVersion) replan('the rules changed')
        else if (meansGone(me.inventory, inv, me.route.slice(me.index))) replan('a tool or the blocks the route uses are gone')
        else if ((goal.moves() && me.complete && !goal.isEnd(me.route[me.route.length - 1])) || me.worse) {
          // The goal moved and the route no longer ends at it, or a zone made the rest of the route worse. The body
          // walks on along the route it has, and the new route is searched meanwhile and taken when it is found.
          if (!me.next && stands()) {
            const made = makeSearch(goal, options, penalties, clock)
            me.next = { search: made.search, movements: made.movements, inventory: inv, bound: made.bound }
            report.replans++
            note('nav_route', { why: me.worse ? 'a zone made the route worse' : 'the goal moved', goal: goal.text })
          }
          const found = me.next ? me.next.search.compute() : { status: 'partial' }
          if (found.status === 'success') {
            const next = me.next; me.next = null
            // (The search began some ticks ago, from the cell the body was in then: the steps it has made since are made.)
            let made = 0
            for (let k = Math.min(found.path.length - 1, 6); k >= 0; k--) { if (found.path[k].x === here.x && found.path[k].y === here.y && found.path[k].z === here.z) { made = k + 1; break } }
            me.route = found.path; me.index = made; me.stepBegan = Date.now(); me.stepFrom = here
            me.movements = next.movements; me.inventory = next.inventory; me.complete = true; me.worse = false
            me.zonesSeen = zonesVersion; me.zonesAt = zones
          } else if (found.status !== 'partial') { me.next = null; me.worse = false }     // (no way to it from there: the route the body has is walked on)
        } else if (me.next) me.next = null
      }
      // In a cell of the goal: the walk is over, or, for a goal that is a point, the rest of the way is to the point.
      if (!me.route && !me.searching && goal.isEnd(here) && bot.entity.onGround) {
        if (!goal.at) return me.finish({ arrived: true })
        me.route = []; me.index = 0; me.complete = true; me.stepFrom = here
      }
      if (!me.route) {
        if (!me.searching) {
          if (!stands()) { hold(); return }
          const made = makeSearch(goal, options, penalties, clock)
          me.searching = made.search; me.movements = made.movements; me.version = rulesVersion; me.inventory = inv; me.bound = made.bound
          me.zonesSeen = zonesVersion; me.zonesAt = zones; me.worse = false
          me.searchBegan = Date.now()
          report.replans++
          note('nav_route', { why: me.why, goal: goal.text })
        }
        const result = me.searching.compute()
        if (result.status !== 'success') {
          // No whole route yet. The part that gets nearest the goal is worth walking when it gets clearly nearer
          // than the body is and than any part walked before (by the search's own measure, in seconds).
          const end = result.path[result.path.length - 1]
          const left = end ? goal.heuristic(end) : Infinity
          const nearer = !!end && left < goal.heuristic(new Move(here.x, here.y, here.z, 0, 0)) - 0.5 && left < me.nearest - 0.5
          if (result.status === 'partial' && !(nearer && Date.now() - me.searchBegan > SEARCH_PART_MS)) { hold(); return }
          if (!nearer) {
            me.searching = null
            const rules = [...active.keys()].join(', ') || 'no rule in force'
            return me.finish({ arrived: false, why: result.status === 'noPath'
              ? `no route: every way is closed or forbidden (${rules})`
              : `no route to the goal was found in ${+((me.bound || SEARCH_TOTAL_MS) / 1000).toFixed(1)} s of searching from here (${rules})${ruleText(clock)}` })
          }
          me.nearest = left
        }
        me.searching = null
        me.route = result.path; me.index = 0; me.stepBegan = Date.now(); me.stepFrom = here
        me.complete = result.status === 'success'
        if (report.expected_seconds === null) report.expected_seconds = count(result.path).seconds
      }
      const route = me.route
      if (me.index >= route.length) {
        if (me.next) {
          // The route the body had is walked and the new one is not found yet: the body waits for it.
          me.searching = me.next.search; me.movements = me.next.movements; me.inventory = me.next.inventory; me.bound = me.next.bound
          me.searchBegan = Date.now(); me.next = null; me.route = null
          hold(); return
        }
        if (!me.complete) return replan('the found part of the route was walked')
        if (goal.isEnd(here)) return goal.at ? toPoint(bot.entity.position) : me.finish({ arrived: true })
        return replan('the route ended short of the goal')
      }
      const move = route[me.index]
      const from = me.index > 0 ? route[me.index - 1] : me.stepFrom
      // A block placed ahead under the way (a bridge) is placed as the body walks: the click is on the side of the
      // block under it, sent at once, and the keys stay down.
      // Only a block under the way is placed so: one at the height of the body's feet or above (the block a step up
      // goes onto) is in the way the body walks, so it is placed standing, the body kept out of its cell (work).
      const ahead = move.toBreak.length === 0 && move.toPlace.length > 0 && move.toPlace.every(p => !p.useOne && !p.jump && p.y + p.dy < from.y)
      if (ahead && !me.placing) placeAhead(from, move)
      // (placeAhead runs on its own, but up to its first wait it runs now: a placement it finds impossible at once
      // fails the step here, and the route this tick was walking is no longer the walk's.)
      if (me.route !== route) return
      // What the step needs done standing: a dig (it takes its time), a block under the body (in a jump).
      if (!ahead && (move.toBreak.length || move.toPlace.some(p => !p.useOne))) {
        if (!bot.entity.onGround && !bot.entity.isInWater) { release(); return }
        work(from, move)
        return
      }
      const pos = bot.entity.position
      // (While the block of a bridge is on its way the step cannot be made yet: the keys below take the body on
      // toward it for as long as it can still stop on what is there.)
      const grounded = bot.entity.onGround || !!bot.entity.isInWater
      // Where the body is on the route.
      const now = progress(pos, grounded, me.index)
      if (now > me.index) {
        if (now === me.index + 1 && move.base > 0) learn('walk', move.base, (Date.now() - me.stepBegan) / 1000)
        report.steps += now - me.index; me.index = now; me.stepBegan = Date.now()
        if (now >= route.length && me.complete && !goal.where && !goal.at) { release(); if (grounded) return me.finish({ arrived: true }) }
        bot.setControlState('jump', false)      // (a jump is pressed for its one tick: the keys of the next step come with the next tick)
        return
      }
      // A step that takes far longer than it should has failed (what was expected of it, three times over, and a second).
      if (Date.now() - me.stepBegan > (move.cost * 3 + 1.5) * 1000 + (move.y < from.y ? 1500 : 0)) return fail(from, move, 'the body did not get there')
      // This tick's keys: those of the first way of pressing them that, by the game's own physics in the world as it
      // is now, makes the step and leaves the body standing on the route (choose). That is the one judgement of
      // whether the route still holds. Where no way does and the body stands (on the ground or in water), the route
      // no longer holds from here, whatever made it so (a block put in its way, a landing elsewhere, a hit): the step
      // has failed when the body is at it, and the route is searched again from where the body is when it is not.
      // Only while a block of a bridge ahead is still being placed does the body go on toward it without a way
      // (approach): the step cannot be made before the block is there. In the air no way is held to: below.
      me.aims = new Map()
      const head = steer(pos, bot.entity.onGround, !!bot.entity.isInWater, me.index)
      const plan = choose()
      const bridging = move.toPlace.length > 0
      const onward = plan || !bridging ? null : approach(head.swim)
      if (!plan && !bridging && grounded) {
        const atStep = [from, move].some(m => m.x === here.x && m.y === here.y && m.z === here.z)
        if (atStep && move.parkour && !move.runupTaken && here.x === from.x && here.y === from.y && here.z === from.z) {
          // At the take-off of a jump the body is not fast enough for along it (it came in from the side, or stood):
          // it takes the run-up the jump needs, the cells behind the take-off and back, then jumps.
          const k = runupNeeded(from, move, sprints(), null)
          if (k !== null) {
            move.runupTaken = true
            const dx = Math.sign(move.x - from.x); const dz = Math.sign(move.z - from.z)
            const cell = (j) => { const m = new Move(from.x - dx * j, from.y, from.z - dz * j, from.remainingBlocks, 1 / SPEED.walk); m.base = m.cost; return m }
            const cells = []
            for (let j = 1; j <= k; j++) cells.push(cell(j))
            for (let j = k - 1; j >= 0; j--) cells.push(cell(j))
            if (k === 0) cells.push(cell(0))
            cells[k === 0 ? 0 : k - 1].still = true      // (where the run begins, at rest)
            route.splice(me.index, 0, ...cells); me.stepBegan = Date.now()
            note('nav_route', { why: `a run-up of ${k} cell${k === 1 ? '' : 's'} before the jump to ${move.x}, ${move.y}, ${move.z}`, goal: goal.text })
            return
          }
        }
        if (atStep) return fail(from, move, 'no pressing of the keys makes this step from where the body stands (forward at a run or at a walk, let go of at a tick, with a jump now or in the next ' + JUMP_WITHIN + ' ticks or with none)')
        return replan('the body is off the route')
      }
      let keys = plan ? pressed(plan, 0, head.swim) : (onward || pressed(null, 0, head.swim))
      // One judgement for every key there is to press, by the game's own physics from the body as it is now (its
      // speed too, after a hit): what holds is what has the body come to stand on the route. Something flies at it,
      // or no planned way holds any more (the body is thrown, or misses a jump): the other ways of pressing the keys
      // (a step to a side, back, a jump, at a run), held for some ticks before the route is followed again, are
      // weighed, and of those that stand on the route the one met least by what flies, then the quickest, is pressed.
      const thrown = !plan && !onward
      if (incoming.length || thrown) {
        let best = foresee(plan, null, 0)
        if (best.hit > 0 || thrown) {
          const t0 = performance.now(); let found = false
          for (const held of thrown ? [AHEAD_MOST, ...HELD] : HELD) {
            for (const side of SIDESTEPS) {
              if (performance.now() - t0 > RESCUE_MS) break
              const out = foresee(plan || RUN, side, held)
              if (better(out, best)) { best = out; keys = side; found = true }
            }
          }
          if (found && thrown) report.rescued++
        }
        if (SIDESTEPS.includes(keys) && !thrown) report.dodged++
      }
      bot.look(head.yaw, 0, true)
      // (A block being placed meanwhile holds sneak down: bot.placeBlock.)
      for (const key of KEYS) bot.setControlState(key, !!keys[key] || (key === 'sneak' && bot.placing > 0))
      // (A probe may watch the walk's every tick: bot._navDebug, read only, never set in a run.)
      if (bot._navDebug) {
        const cell = (m) => m ? { at: [m.x, m.y, m.z], parkour: !!m.parkour, dig: m.toBreak.length, place: m.toPlace.length } : null
        const trace = []
        if (plan && me.chosen && me.chosen.upTo !== null) outcome(plan, me.chosen.upTo, trace)
        const v = bot.entity.velocity
        try {
          bot._navDebug({ at: [+pos.x.toFixed(2), +pos.y.toFixed(2), +pos.z.toFixed(2)], vel: [+v.x.toFixed(3), +v.y.toFixed(3), +v.z.toFixed(3)], ground: bot.entity.onGround,
            index: me.index, of: route.length, from: cell(from), step: cell(move), next: [1, 2, 3].map(k => cell(route[me.index + k])),
            plan, chosen: me.chosen, thrown, incoming: incoming.length, keys: KEYS.filter(k => keys[k]), yaw: +head.yaw.toFixed(3),
            target: head.target ? [+head.target.x.toFixed(2), +head.target.y.toFixed(2), +head.target.z.toFixed(2)] : null, hurtNow: hurting(pos), trace })
        } catch (e) {}
      }
    }

    // ---- One measure for the walk, the keys and the look ahead: how far along the route the body is, and the
    // seconds from there to the route's end.
    const middle = (m) => new Vec3(m.x + 0.5, m.y, m.z + 0.5)
    const before = (index) => index > 0 ? me.route[index - 1] : me.stepFrom
    const pending = (m) => m.toBreak.length > 0 || m.toPlace.length > 0
    const standing = (m) => m.toBreak.length > 0 || m.toPlace.some(p => p.jump)      // (what a step is done standing for)
    // The cells the body has to stand on at their middle: one that work is done standing from, and the last cell
    // of a route to a goal that does not move (the end of a route to a goal that moves is not the goal).
    const exact = (k) => !!me.route[k].still || (k === me.route.length - 1 ? !goal.where : standing(me.route[k + 1]))
    const sprints = () => options.sprint !== false && bot.food > 6

    // The step a body at `pos` has still to make, given the one it had (`index`). A step is made when the body is
    // at the step's height (on the ground there, unless the step is plain walking; a step of plain walking also
    // above it by no more than a jump rises, 1.3) and has come to its cell's
    // middle along the step, or past it: the body never turns back to stand on a middle it has gone by. Only a
    // cell it has to stand on exactly is made at its middle alone.
    function progress (pos, grounded, index) {
      const route = me.route
      for (let k = Math.min(route.length - 1, index + 3); k >= index; k--) {
        const m = route[k]
        const a = before(k)
        const plain = m.y === a.y && !m.parkour
        // (A step of plain walking is also made above its height, by no more than a jump rises: the body in the air
        // there is on its way to a later step.)
        if (plain ? !(pos.y - m.y > -0.6 && pos.y - m.y < 1.3) : Math.abs(pos.y - m.y) >= 0.6) continue
        if (route.slice(index, k + 1).some(pending)) continue
        if (route.slice(index, k).some(m => m.still)) continue      // (a cell to come to rest on is not gone by)
        if (!(grounded || plain)) continue
        const flat = Math.hypot(m.x + 0.5 - pos.x, m.z + 0.5 - pos.z)
        if (exact(k)) { if (flat <= 0.35) return k + 1; continue }
        if (flat <= 0.75) return k + 1
        if (flat >= 1.6) continue
        const dx = m.x - a.x; const dz = m.z - a.z; const length = Math.hypot(dx, dz)
        if (length > 0 && ((pos.x - m.x - 0.5) * dx + (pos.z - m.z - 0.5) * dz) / length >= 0) return k + 1
      }
      return index
    }
    // Off the route: farther from the step and from the one before than a step is long, or standing below both.
    function offRoute (pos, grounded, index) {
      const at = Math.min(index, me.route.length - 1)
      const move = me.route[at]; const from = before(at)
      if (Math.hypot(pos.x - move.x - 0.5, pos.z - move.z - 0.5) > 3.5 && Math.hypot(pos.x - from.x - 0.5, pos.z - from.z - 0.5) > 3.5) return true
      return grounded && pos.y < Math.min(move.y, from.y) - 1.5
    }
    // The seconds the route still takes from a body at `pos` that has step `index` to make.
    function left (pos, index) {
      const route = me.route
      if (index >= route.length) return 0
      let seconds = Math.hypot(route[index].x + 0.5 - pos.x, route[index].z + 0.5 - pos.z) / SPEED.sprint
      for (let k = index + 1; k < route.length; k++) seconds += route[k].cost
      return seconds
    }
    // Where the head of a body at `pos` with step `index` to make is turned: on toward the step's cell (the
    // farthest cell of the route that is plain walking in a line from here). And whether it swims up (in water the
    // jump key is held for a step that does not go down: that is swimming, not a jump).
    function steer (pos, onGround, inWater, index) {
      const route = me.route; const move = route[index]; const from = before(index)
      let target = middle(move)
      if (move.y === from.y && !move.parkour) {
        let aim = me.aims.get(index)
        if (aim === undefined) {
          aim = null
          for (let k = index + 1; k < Math.min(route.length, index + 4); k++) {
            const next = route[k]
            if (next.y !== move.y || pending(next) || next.parkour || (k === index + 1 && standing(next))) break
            aim = middle(next)
            if (k < route.length - 1 && (route[k + 1].y !== next.y || standing(route[k + 1]))) break
          }
          if (aim && !lineWalkable(pos, aim)) aim = null
          me.aims.set(index, aim)
        }
        if (aim) target = aim
      }
      const flat = Math.hypot(target.x - pos.x, target.z - pos.z)
      const tight = exact(index)
      // The head is turned along the route. Far from the point the body goes to, that is the direction to the
      // point. Within 0.6 of it (in the air over a lower cell, coming up onto a higher one, going by a middle) the
      // direction to the point turns round from one tick to the next, so the head keeps the direction of the step
      // itself. Only a cell the body has to stand on exactly is steered to up to its middle.
      // Before a step down the head is turned to the middle of the lower cell for as long as the body stands on
      // the ground above; once it falls the head keeps the step's direction. A middle the body has gone by along
      // the step is not turned back to, as it is not stood on again (progress), unless it has to be stood on.
      const down = move.y < from.y && !move.parkour
      const sx = move.x - from.x; const sz = move.z - from.z
      const past = (sx || sz) && (pos.x - target.x) * sx + (pos.z - target.z) * sz >= 0
      const along = !tight && (sx || sz) && (past || (flat < 0.6 && !(down && onGround)))
      const yaw = along ? Math.atan2(-sx, -sz) : Math.atan2(-(target.x - pos.x), -(target.z - pos.z))
      return { yaw, target, swim: inWater && !move.parkour && move.y >= from.y }
    }

    // ---- The keys. A way of pressing them is: forward at a run or at a walk, and a jump at one tick from now or
    // none. The keys of tick `t` of a way (of no way: none), for a body that swims up or does not:
    // (A way may let go of forward at a tick, `stopAt`: from then on only its jump, if it has one then.)
    const pressed = (plan, t, swim) => !plan ? { jump: swim }
      : t < (plan.stopAt === undefined ? Infinity : plan.stopAt) ? { forward: true, sprint: plan.sprint && sprints(), jump: swim || plan.jumpAt === t }
        : { jump: swim || plan.jumpAt === t }
    // One tick of the game's own physics for a body in `state` that presses `keys` with its head at `yaw`.
    function advance (state, keys, yaw) {
      state.control = { forward: !!keys.forward, back: !!keys.back, left: !!keys.left, right: !!keys.right, jump: !!keys.jump, sprint: !!keys.sprint, sneak: false }
      state.yaw = yaw
      bot.physics.simulatePlayer(state, bot.world)
    }
    // A body that is where it cannot come back to the route from: in a forbidden cell, off the route, or fallen below
    // the step it has to make and the one before. (What hurts is not counted here but as the way's exposure: outcome.)
    function lost (state, index) {
      const at = Math.min(index, me.route.length - 1)
      const p = state.pos
      if (p.y < Math.min(me.route[at].y, before(at).y) - 1.5) return true
      return !allowed(p) || offRoute(p, state.onGround || state.isInWater, index)
    }
    // Every way is judged over the same ticks, AHEAD_MOST: a way that comes to rest sooner stays where it rests for the
    // ticks left. The exposure of pressing no key at all over them, from the body as it is now, is the measure a way
    // is held to: no way may keep the body longer in what hurts than standing does.
    function stillExposure () {
      const state = new PlayerState(bot, {}); let hurt = 0
      for (let t = 0; t < AHEAD_MOST; t++) { advance(state, {}, state.yaw); hurt += hurting(state.pos) }
      return hurt
    }
    // What comes of the way `plan`, from the body as it is now, by the game's own physics: the body presses its
    // keys, the head turned as the route turns it, until it has made step `upTo`; then no key is pressed, until it
    // has come to rest. The way holds when the body then stands on the route with step `upTo` still made (a cell
    // it has to stand on exactly is made at its middle alone: there it has to have come to rest). Returns {ok,
    // failedAt: the tick at which it was lost, Infinity when it only did not make the step in time}.
    function outcome (plan, upTo, trace) {
      const state = new PlayerState(bot, {})
      let index = me.index; let made = false; let hurt = 0; let ticks = 0
      for (let t = 0; t < AHEAD_MOST; t++) {
        const head = steer(state.pos, state.onGround, state.isInWater, index)
        advance(state, pressed(plan, t, head.swim), head.yaw); ticks++
        if (trace) trace.push([+state.pos.x.toFixed(2), +state.pos.y.toFixed(2), +state.pos.z.toFixed(2), hurting(state.pos), state.onGround ? 1 : 0, index])
        if (lost(state, index)) return { ok: false, failedAt: t, hurt }
        hurt += hurting(state.pos)
        index = progress(state.pos, state.onGround || state.isInWater, index)
        if (index > upTo) { made = true; break }
      }
      if (!made) return { ok: false, failedAt: Infinity, hurt }
      for (let t = 0; t < REST_MOST && !state.isInWater && !(state.onGround && Math.hypot(state.vel.x, state.vel.z) < 0.003); t++) {
        advance(state, {}, state.yaw); ticks++
        if (trace) trace.push([+state.pos.x.toFixed(2), +state.pos.y.toFixed(2), +state.pos.z.toFixed(2), hurting(state.pos), state.onGround ? 1 : 0, index, 'rest'])
        if (lost(state, Math.min(index, me.route.length - 1))) return { ok: false, failedAt: Infinity, hurt }
        hurt += hurting(state.pos)
      }
      hurt += Math.max(0, AHEAD_MOST - ticks) * hurting(state.pos)
      const grounded = state.onGround || state.isInWater
      return { ok: grounded && (state.isInWater || Math.hypot(state.vel.x, state.vel.z) < 0.003) && progress(state.pos, grounded, me.index) > upTo, failedAt: Infinity, hurt }
    }
    // The way of pressing the keys for this tick: the first that holds, tried in this order: at a run before at a
    // walk; with no jump before a jump now, a jump one tick from now, and so on. (A jump at a tick after the one
    // at which the way with no jump is lost is lost with it: not tried.) Where the step after the one being made
    // leaves the ground (a gap, a block up), its jump may have to come while this step is still being made: the
    // ways are judged up to that step first, and up to the step being made if none holds that far. Last, forward let
    // go of at a tick, the latest first: a body that keeps pressing it goes on past where it has to come down
    // (onto a place a block wide, below), as a player lets go of it once over the edge.
    // Of the ways that make the step, one holds only where it keeps the body no longer in what hurts than standing
    // still would (stillExposure); of those, the one with the least exposure, in the order above where they are
    // alike. (A body out of harm: only ways that touch nothing that hurts hold, and the first of them is taken. A body
    // already in it: the way out of it soonest.)
    function choose () {
      const route = me.route; const i = me.index
      const leaves = (k) => !!route[k].parkour || route[k].y > before(k).y
      // (Only straight on: the jump of a step that turns from this one is made from its own take-off cell, the body
      // turned there first. A jump begun a cell early across the turn cuts the corner, and lands on the edge of what
      // holds it: by hundredths, which the game's movement does not keep to.)
      const dir = (k) => { const a = before(k); const m = route[k]; return [Math.sign(m.x - a.x), Math.sign(m.z - a.z)] }
      const straight = i + 1 < route.length && dir(i)[0] === dir(i + 1)[0] && dir(i)[1] === dir(i + 1)[1]
      const far = !leaves(i) && i + 1 < route.length && leaves(i + 1) && !pending(route[i + 1]) && straight
      const base = stillExposure()
      for (const upTo of far ? [i + 1, i] : [i]) {
        let best = null
        const take = (plan, out) => {
          if (!out.ok || out.hurt > base || (best && best.hurt <= out.hurt)) return false
          best = { plan, hurt: out.hurt }
          return out.hurt === 0
        }
        search: {
          for (const sprint of sprints() ? [true, false] : [false]) {
            const plain = outcome({ sprint, jumpAt: null }, upTo)
            if (take({ sprint, jumpAt: null }, plain)) break search
            for (let n = 0; n <= JUMP_WITHIN && n <= plain.failedAt; n++) {
              if (take({ sprint, jumpAt: n }, outcome({ sprint, jumpAt: n }, upTo))) break search
            }
          }
          for (const sprint of sprints() ? [true, false] : [false]) {
            for (let n = JUMP_WITHIN; n >= 0; n--) {
              if (take({ sprint, jumpAt: null, stopAt: n }, outcome({ sprint, jumpAt: null, stopAt: n }, upTo))) break search
            }
          }
        }
        if (best) { me.chosen = { upTo, hurt: best.hurt, base }; return best.plan }
      }
      me.chosen = { upTo: null, hurt: null, base }
      return null
    }
    // Forward for this tick, at a run or at a walk, where the body can still stop on the route after it: pressed
    // for one tick and no key after that, by the game's own physics, it comes to rest without having been lost.
    function approach (swim) {
      const still = (state) => state.isInWater || (state.onGround && Math.hypot(state.vel.x, state.vel.z) < 0.003)
      for (const sprint of sprints() ? [true, false] : [false]) {
        const state = new PlayerState(bot, {})
        const keys = { forward: true, sprint, jump: swim }
        advance(state, keys, steer(state.pos, state.onGround, state.isInWater, me.index).yaw)
        const base = stillExposure(); let hurt = hurting(state.pos)
        let held = !lost(state, me.index)
        for (let t = 0; held && t < REST_MOST && !still(state); t++) { advance(state, {}, state.yaw); held = !lost(state, me.index); hurt += hurting(state.pos) }
        if (hurt > base) held = false
        if (held && still(state)) return keys
      }
      return null
    }
    // The cells of the straight line from the body (in cell `here`, at `pos`) to `to`, at the body's height: the
    // route to a goal that is straight ahead. (The line is walkable: lineWalkable.)
    function lineCells (here, pos, to) {
      const cells = []; let last = here
      const length = Math.hypot(to.x - pos.x, to.z - pos.z); const n = Math.ceil(length * 4)
      for (let k = 1; k <= n; k++) {
        const x = Math.floor(pos.x + (to.x - pos.x) * k / n); const z = Math.floor(pos.z + (to.z - pos.z) * k / n)
        if (x === last.x && z === last.z) continue
        const cell = new Move(x, here.y, z, 0, Math.hypot(x - last.x, z - last.z) / SPEED.sprint)
        cells.push(cell); last = cell
      }
      return cells
    }
    // What comes of pressing `keys` for `held` ticks and going on by the way `plan` after that (of the way from the
    // first, with no keys given), by the game's own physics, until the body stands: how often something that
    // flies meets it, whether it left the route or where it may be, and the seconds to the route's end.
    function foresee (plan, keys, held) {
      const state = new PlayerState(bot, {})
      let index = me.index; let hit = 0; let hurt = 0; let t = 0
      for (; t < AHEAD_MOST && index < me.route.length; t++) {
        const head = steer(state.pos, state.onGround, state.isInWater, index)
        const press = keys && t < held ? (keys.sprint && !sprints() ? { ...keys, sprint: false } : keys) : pressed(plan, t, head.swim)
        advance(state, press, head.yaw)
        const p = state.pos
        for (const f of incoming) {
          const fx = f.position.x + f.velocity.x * (t + 1); const fy = f.position.y + f.velocity.y * (t + 1); const fz = f.position.z + f.velocity.z * (t + 1)
          const dx = Math.max(Math.abs(fx - p.x) - 0.3, 0); const dz = Math.max(Math.abs(fz - p.z) - 0.3, 0)
          const dy = fy < p.y ? p.y - fy : fy > p.y + 1.8 ? fy - (p.y + 1.8) : 0
          if (dx * dx + dy * dy + dz * dz <= (f.radius + 0.25) ** 2) hit++
        }
        const grounded = state.onGround || state.isInWater
        if (!allowed(p) || offRoute(p, grounded, index)) return { hit, hurt, off: true, seconds: Infinity }
        hurt += hurting(p)
        index = progress(p, grounded, index)
        if (grounded && t + 1 >= AHEAD) { t++; break }
      }
      const grounded = state.onGround || state.isInWater
      return { hit, hurt, off: !grounded, seconds: t / 20 + left(state.pos, index) }
    }
    // (Standing on the route, before not met by what flies, before the least time in what hurts, before the seconds:
    // a way that loses the route is taken only when every way does.)
    function better (a, b) {
      if (a.off !== b.off) return !a.off
      if (a.hit !== b.hit) return a.hit < b.hit
      if (a.hurt !== b.hurt) return a.hurt < b.hurt
      return a.seconds < b.seconds - 0.01
    }
    function hold () { for (const key of ['forward', 'back', 'left', 'right', 'sprint', 'jump']) bot.setControlState(key, false) }
    // The last of a walk to a point, from a cell of the goal: to within its range of the point itself, by the game's
    // own physics: forward at a walk, head to the point, for the fewest ticks after which the body comes to rest within
    // range. Where no number of ticks does and the body stands still, it cannot come nearer: the walk says so.
    function toPoint (pos) {
      const p = goal.point
      if (!bot.entity.onGround && !bot.entity.isInWater) { hold(); return }
      if (goal.at(pos)) return me.finish({ arrived: true })
      const to = (q) => Math.atan2(-(p.x - q.x), -(p.z - q.z))
      for (let n = 1; n <= JUMP_WITHIN; n++) {
        const state = new PlayerState(bot, {})
        for (let t = 0; t < n + REST_MOST; t++) {
          advance(state, t < n ? { forward: true } : {}, t < n ? to(state.pos) : state.yaw)
          if (t >= n && state.onGround && Math.hypot(state.vel.x, state.vel.z) < 0.003) break
        }
        if (state.onGround && standable(state.pos) && goal.at(state.pos)) {
          bot.look(to(pos), 0, true)
          for (const key of KEYS) bot.setControlState(key, key === 'forward')
          return
        }
      }
      hold()
      if (Math.hypot(bot.entity.velocity.x, bot.entity.velocity.z) >= 0.003) return
      const d = Math.hypot(pos.x - p.x, pos.z - p.z)
      me.finish({ arrived: false, why: `the body cannot come within ${goal.range} of the point: it stands ${d.toFixed(2)} from it across` })
    }
    // Whether the body can go straight from `a` to `b` at one height: floor under every cell of the line, nothing in it.
    function lineWalkable (a, b) {
      const n = Math.ceil(Math.hypot(b.x - a.x, b.z - a.z) * 2)
      for (let k = 1; k <= n; k++) {
        const x = a.x + (b.x - a.x) * k / n; const z = a.z + (b.z - a.z) * k / n
        for (const [ox, oz] of [[0.3, 0.3], [-0.3, 0.3], [0.3, -0.3], [-0.3, -0.3]]) {
          const cell = new Vec3(Math.floor(x + ox), Math.floor(b.y + 0.001), Math.floor(z + oz))
          const feet = bot.blockAt(cell, false); const head = bot.blockAt(cell.offset(0, 1, 0), false); const floor = bot.blockAt(cell.offset(0, -1, 0), false)
          if (!feet || !head || !floor) return false
          if (feet.boundingBox !== 'empty' || head.boundingBox !== 'empty' || floor.boundingBox !== 'block') return false
          if (HURTS.test(feet.name) || HURTS.test(head.name)) return false     // (lava and fire have no box: they are not in the way, they burn)
          if (/lava|fire|magma|cactus|campfire/.test(floor.name) || zoneCost(cell.x, cell.y, cell.z) >= FORBID) return false
        }
      }
      return true
    }
    bot.on('physicsTick', tick); bot.on('forcedMove', pulled); bot.on('entityHurt', hurt); bot.on('death', died)
    return { done, stop: (why) => me.finish({ arrived: false, why: why || 'stopped' }) }
  }

  return { go, path, define, undefine, avoid, unavoid, dropOwner, listed, readHazards, walking: () => !!walk, stop: (why) => { if (walk) walk.finish({ arrived: false, why }) } }
}
