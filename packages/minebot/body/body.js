// The body: a Mineflayer bot and the code that runs on it, in a process of its own.
//
// The bridge (bridge.js) starts this process and talks to it over the process channel. The
// caller's code gets the Mineflayer bot behind a gate (see "running the caller's code"): it
// reads and acts as on the bot itself, and waits there while other code has the body. What
// keeps the process safe is its boundary: code that does not end when told, or keeps the process busy, or stops
// the body's physics, is ended by ending this process; the bridge starts a new one and the
// body logs in again where it stood. Nothing here knows how to play.

const fs = require('fs')
const path = require('path')
const EventEmitter = require('events')
const mineflayer = require('mineflayer')
const { Vec3 } = require('vec3')
const { applyServerDigRules } = require('./dig_rules')
const makeNav = require('./nav')

// The physics the bot moves by clips a move against a block only when the body's box is
// exactly at or before the block's face. A body pushed against a wall is put at face + 0.3,
// and for some faces (face + 0.3) - 0.3 comes out a hair less than the face (2.3 - 0.3 is
// 1.9999999999999998): on the next tick the box counts as already past the face, nothing is
// clipped, and the body walks into the block. The game puts it back, every tick, for as long
// as the key is held: it stands and twitches, off the ground, and cannot jump. The game itself
// compares with a margin of 1e-7; so do these.
{
  const AABB = require('prismarine-physics/lib/aabb')
  const E = 1e-7
  AABB.prototype.computeOffsetX = function (other, offsetX) {
    if (other.maxY > this.minY + E && other.minY < this.maxY - E && other.maxZ > this.minZ + E && other.minZ < this.maxZ - E) {
      if (offsetX > 0.0 && other.maxX <= this.minX + E) offsetX = Math.min(this.minX - other.maxX, offsetX)
      else if (offsetX < 0.0 && other.minX >= this.maxX - E) offsetX = Math.max(this.maxX - other.minX, offsetX)
    }
    return offsetX
  }
  AABB.prototype.computeOffsetY = function (other, offsetY) {
    if (other.maxX > this.minX + E && other.minX < this.maxX - E && other.maxZ > this.minZ + E && other.minZ < this.maxZ - E) {
      if (offsetY > 0.0 && other.maxY <= this.minY + E) offsetY = Math.min(this.minY - other.maxY, offsetY)
      else if (offsetY < 0.0 && other.minY >= this.maxY - E) offsetY = Math.max(this.maxY - other.minY, offsetY)
    }
    return offsetY
  }
  AABB.prototype.computeOffsetZ = function (other, offsetZ) {
    if (other.maxX > this.minX + E && other.minX < this.maxX - E && other.maxY > this.minY + E && other.minY < this.maxY - E) {
      if (offsetZ > 0.0 && other.maxZ <= this.minZ + E) offsetZ = Math.min(this.minZ - other.maxZ, offsetZ)
      else if (offsetZ < 0.0 && other.minZ >= this.maxZ - E) offsetZ = Math.max(this.maxZ - other.minZ, offsetZ)
    }
    return offsetZ
  }
}

const HOST = process.env.MC_HOST || '127.0.0.1'
const PORT = Number(process.env.MC_PORT || 25565)
const USER = process.env.MC_USER || 'minebot'
const VERSION = process.env.MC_VERSION || '1.16.1'
// How the body logs in: offline (the server checks no account), or microsoft (the account's owner signs in once
// with a code the body is given; the tokens are kept in MC_PROFILES, never the password).
const AUTH = process.env.MC_AUTH === 'microsoft' ? 'microsoft' : 'offline'
const STORE = path.resolve(process.env.BRIDGE_STORE || path.join(__dirname, 'store'))

function send (message) { try { if (process.connected) process.send(message) } catch (error) {} }
// (`age`: the world's age in game ticks when it happened: what the game's own clock says.)
function note (kind, data = {}) { send({ ev: 'event', kind, ...data, age: bot && bot.time && bot.time.age !== undefined ? Number(bot.time.bigAge || bot.time.age) : null }) }
function sleep (ms) { return new Promise(resolve => setTimeout(resolve, ms)) }

// The server's console (RCON: MC_RCON_PORT and MC_RCON_PASSWORD, and MC_RCON_HOST where it is not the game's host),
// where whoever owns the server gave the body one, for what
// the body does by the server's commands (bot.fillBucket). One connection, kept; one command at a time; its answer.
const rcon = (() => {
  const port = Number(process.env.MC_RCON_PORT || 0); const password = process.env.MC_RCON_PASSWORD || ''
  let socket = null; let ready = null; let buffer = Buffer.alloc(0); let waiting = null; let next = 1; let queue = Promise.resolve()
  const lost = (error) => {
    socket = null; ready = null; buffer = Buffer.alloc(0)
    if (waiting) { const w = waiting; waiting = null; w.reject(error) }
  }
  const send = (kind, body) => new Promise((resolve, reject) => {
    const text = Buffer.from(body, 'utf8'); const packet = Buffer.alloc(14 + text.length)   // (two zero bytes end it)
    packet.writeInt32LE(10 + text.length, 0); packet.writeInt32LE(next++, 4); packet.writeInt32LE(kind, 8); text.copy(packet, 12)
    const timer = setTimeout(() => { if (socket) socket.destroy(); lost(new Error('the server did not answer a command within 5 s')) }, 5000)
    waiting = { resolve: (got) => { clearTimeout(timer); resolve(got) }, reject: (error) => { clearTimeout(timer); reject(error) } }
    socket.write(packet)
  })
  const read = () => {
    while (buffer.length >= 4 && buffer.length >= 4 + buffer.readInt32LE(0)) {
      const size = buffer.readInt32LE(0)
      const got = { id: buffer.readInt32LE(4), body: buffer.toString('utf8', 12, 4 + size - 2) }
      buffer = buffer.subarray(4 + size)
      if (waiting) { const w = waiting; waiting = null; w.resolve(got) }
    }
  }
  const connect = () => {
    if (ready) return ready
    ready = new Promise((resolve, reject) => {
      if (!port || !password) return reject(new Error('the server takes no commands here (no RCON port and password were given)'))
      const s = require('net').connect({ host: process.env.MC_RCON_HOST || process.env.MC_HOST || '127.0.0.1', port })
      s.on('data', (data) => { buffer = Buffer.concat([buffer, data]); read() })
      s.on('error', (error) => { lost(error); reject(error) })
      s.on('close', () => lost(new Error('the server closed its command port')))
      s.on('connect', async () => {
        socket = s
        try {
          if ((await send(3, password)).id === -1) throw new Error('the server refused the command password')
          resolve()
        } catch (error) { s.destroy(); reject(error) }
      })
    })
    ready.catch(() => { ready = null })
    return ready
  }
  return (command) => {
    const run = queue.then(async () => { await connect(); return (await send(2, command)).body })
    queue = run.catch(() => {})
    return run
  }
})()
function round2 (v) { return typeof v === 'number' && isFinite(v) ? +v.toFixed(2) : null }
function pos (p) { return p ? { x: round2(p.x), y: round2(p.y), z: round2(p.z) } : null }

// ---------------------------------------------------------------- one listener cannot stop the others
//
// Every emitter in this process (the bot, its client, its inventory) calls its listeners
// one after the other; a listener that throws would keep the ones behind it from running,
// and behind the caller's listeners are the body's own physics.
// So each listener runs on its own: what it throws is reported, the rest still run.

const reported = new Map()   // event|message -> {at, more}
function listenerError (event, error) {
  const message = String(error && error.message !== undefined ? error.message : error).slice(0, 200)
  const key = String(event) + '|' + message
  const now = Date.now()
  const entry = reported.get(key)
  if (!entry) {
    if (reported.size > 200) reported.clear()
    reported.set(key, { at: now, more: 0 })
    note('listener_error', { on: String(event), message })
  } else if (now - entry.at > 5000) {
    note('listener_error', { on: String(event), message, again: entry.more + 1 })
    entry.at = now; entry.more = 0
  } else entry.more++
}

const plainEmit = EventEmitter.prototype.emit
// (PLAIN_EMIT=1 leaves the emitters as Node has them: for telling apart what this changes.)
if (process.env.PLAIN_EMIT !== '1') EventEmitter.prototype.emit = function (event, ...parts) {
  const held = this._events && this._events[event]
  if (held === undefined) return plainEmit.call(this, event, ...parts)   // nobody listens: as always ('error' throws)
  const listeners = typeof held === 'function' ? [held] : held.slice()
  for (const listener of listeners) {
    try {
      const out = Reflect.apply(listener, this, parts)
      if (out && typeof out.then === 'function' && typeof out.catch === 'function') out.catch(error => listenerError(event, error))
    } catch (error) { listenerError(event, error) }
  }
  return true
}

// ---------------------------------------------------------------- the bot

let bot = null
let registry = null
let nav = null               // what walks the body (nav.js)
const navDefined = []        // the hazards and route rules given before the body was in the world
let joined = false
let ticks = 0                // physics ticks since this process began
// What the code that runs did to the world, counted as the game reports it, by the channel
// it was done on: {dug: {block: n}, placed: {block: n}, broke: [tool], moved: blocks, pulled_back: n}.
function count (bag, name) { bag[name] = (bag[name] || 0) + 1 }
function summary (did) { return { dug: did.dug, placed: did.placed, broke: did.broke, moved: Math.round(did.moved), pulled_back: did.pulled_back } }
// The bag of the code that runs on `channel` now (at most one code does: see "channels"), or null.
function doing (channel) { const ctx = holder(channel); return ctx ? ctx.did : null }
// {job id: what it did so far} of the code that has not ended.
function doingNow () { const out = {}; for (const ctx of contexts.values()) if (!ctx.over) out[ctx.id] = summary(ctx.did); return out }
const said = []              // the last chat lines, for the line a death comes with
// Senses: values the caller defined, computed here with every state the body reports (20
// times a second), so that what judges the state far from here reads them without asking.
// A sense is the body of a plain function of (bot, Vec3, h) that returns a value. It runs
// between the body's physics ticks, so it has SENSE_MS: one that takes longer SENSE_SLOW
// times running is no longer computed until it is defined again.
const SENSE_MS = Number(process.env.SENSE_MS || 10)
const SENSE_SLOW = 3
const senses = {}            // name -> {fn, slow, error}
const sensesNow = {}         // name -> () => its value at this moment (for the caller's code)

function dimension () { return bot.game ? String(bot.game.dimension) : 'unknown' }

function connect () {
  // (respawn: false: a dead body stays dead until it is told to respawn; when that is, is the agent's to decide.)
  bot = mineflayer.createBot({ host: HOST, port: PORT, username: USER, version: VERSION, auth: AUTH, checkTimeoutInterval: 120000,
    respawn: false,
    ...(AUTH === 'microsoft' ? {
      profilesFolder: process.env.MC_PROFILES || path.join(STORE, 'profiles'),
      // The account's owner is asked to sign in: where, and with which code (the event sign_in).
      onMsaCode: (data) => note('sign_in', { uri: data.verification_uri, code: data.user_code, seconds: data.expires_in })
    } : {}) })
  // A command the body types is recorded as such (whether the game obeys it is the game's to say).
  const say = bot._client.write.bind(bot._client)
  bot._client.write = (name, params) => {
    if (name === 'chat' && params && typeof params.message === 'string' && params.message.startsWith('/')) note('command', { text: params.message.slice(0, 100) })
    // (Since 1.19 a command goes in a packet of its own, without the slash.)
    if ((name === 'chat_command' || name === 'chat_command_signed') && params && typeof params.command === 'string') note('command', { text: ('/' + params.command).slice(0, 100) })
    // (A block in the hand, used on a block: the body places it.)
    const placing = name === 'block_place' && doing('use')
    if (placing && bot.heldItem && bot.registry.blocksByName[bot.heldItem.name]) count(placing.placed, bot.heldItem.name)
    return say(name, params)
  }
  let inHand = null; let stood = null
  bot.on('physicsTick', () => {
    if (bot.heldItem) inHand = bot.heldItem.name
    const at = bot.entity.position
    const moving = doing('move')
    if (moving && stood) { const step = at.distanceTo(stood); if (step < 4) moving.moved += step }   // (a longer step is a teleport)
    stood = at.clone()
  })
  // The game says so when the item in the body's hand breaks.
  bot._client.on('entity_status', (packet) => {
    if (!bot.entity || packet.entityId !== bot.entity.id || packet.entityStatus !== 47 || !inHand) return
    note('tool_broke', { item: inHand })
    const using = doing('use')
    if (using) using.broke.push(inHand)
  })
  // The server puts the body back where it has it (it did not accept a move): said, and counted for the code that moves it.
  bot.on('forcedMove', () => {
    note('pulled_back', { position: pos(bot.entity.position) })
    const moving = doing('move')
    if (moving) moving.pulled_back++
  })
  if (VIEW) mirror()
  // What a 1.16 server puts back into the player's inventory by itself (the items of a
  // crafting grid or the cursor when a window closes) it tells with the window id -2 and
  // the inventory's own slot numbers. The library applies only the newer packet of that
  // meaning, so its picture of the inventory would stay wrong and the server would reject
  // every click made from it. Applied here as that newer packet is.
  const Item = require('prismarine-item')(VERSION)
  bot._client.on('set_slot', (packet) => {
    if (packet.windowId !== -2) return
    const slot = packet.slot <= 8 ? packet.slot + 36 : packet.slot >= 36 && packet.slot <= 39 ? 44 - packet.slot : packet.slot === 40 ? 45 : packet.slot
    try { bot._setSlot(slot, Item.fromNotch(packet.item)) } catch (error) { note('error', { message: 'inventory slot from the server: ' + error.message }) }
  })
  // What is on the cursor a 1.16 server tells with the window id -1 and the slot -1: after a
  // click it refused it says so, with all the slots. The library applies the slots and leaves
  // its cursor as it was: it then believes an item is on the cursor that the game has put back,
  // and the game refuses every click it makes from there on. Applied here.
  bot._client.on('set_slot', (packet) => {
    if (packet.windowId !== -1 || packet.slot !== -1) return
    try {
      const item = Item.fromNotch(packet.item)
      bot.inventory.selectedItem = item
      if (bot.currentWindow) bot.currentWindow.selectedItem = item
    } catch (error) { note('error', { message: 'cursor from the server: ' + error.message }) }
  })
  // A chunk that holds no block at all (the void of the End) the server sends as a whole chunk
  // with no section in it. The library reads that as "forget this chunk", as it meant before
  // 1.9: the body then has no chunk there, its physics do not tick while it stands in it, and a
  // block placed into it is never seen. Kept here as the empty chunk it is. (Added at the login:
  // by then the library's own listener is there, and this one runs after it.)
  const Chunk = require('prismarine-chunk')(VERSION)
  bot.once('login', () => {
    bot._client.on('map_chunk', (packet) => {
      if (packet.bitMap || !packet.groundUp || bot.world.getColumn(packet.x, packet.z)) return
      try {
        const column = new Chunk({ minY: bot.game.minY, worldHeight: bot.game.height })
        if (packet.biomes !== undefined) column.loadBiomes(packet.biomes)
        bot.world.setColumn(packet.x, packet.z, column)
      } catch (error) { note('error', { message: 'an empty chunk from the server: ' + error.message }) }
    })
  })
  // The library ends a dig by its own timer: it sets the block to air at once and does not read
  // the server's answer to the dig (acknowledge_player_digging: the block as the server has it
  // now). Where its dig time is shorter than the server's (an axe on leaves), the server keeps
  // the block, and the body walks into a block it believes gone and is sent back without end.
  // The server's answer is taken as the block's state.
  bot._client.on('acknowledge_player_digging', (packet) => {
    try {
      const at = new Vec3(packet.location.x, packet.location.y, packet.location.z)
      const now = bot.world.getBlockStateId(at)
      if (now === undefined || now === packet.block) return
      if (typeof bot._updateBlockState === 'function') bot._updateBlockState(at, packet.block)
      else bot.world.setBlockStateId(at, packet.block)
      if (!packet.successful) note('dig_refused', { at: [at.x, at.y, at.z], block: bot.registry.blocksByStateId[packet.block]?.name })
    } catch (error) { note('error', { message: 'a dig answer from the server: ' + error.message }) }
  })
  // A player who goes through the End's exit portal is taken out of the End, told "win game",
  // and put into the overworld only when the client asks to respawn. The library asks only when
  // the credits are to be shown (the first time): every later time the body would stay out of
  // the world, with a server that sends it nothing. Asked here every time.
  bot._client.on('game_state_change', (packet) => {
    if (packet.reason !== 4 && packet.reason !== 'win_game') return
    try { bot._client.write('client_command', { actionId: 0 }) } catch (error) { note('error', { message: 'leaving the End: ' + error.message }) }
  })
  // What the game tells every player in the world at once, wherever they are (its "global"
  // world events): told on as it is, with the game's clock. The dragon's death is one of them,
  // and it is the game's only word on it when no player's own hit is among what killed it (the
  // game then gives no advancement for it).
  const TOLD = { 1023: 'a Wither was spawned', 1028: 'the Ender Dragon died', 1038: 'an End portal was opened' }
  bot._client.on('world_event', (packet) => {
    if (packet.global && TOLD[packet.effectId]) note('told', { what: TOLD[packet.effectId] })
  })
  // The body is in the world from its first spawn; or, when it logs in dead (it died and its
  // process was started again before it was told to respawn), from the death the game reports
  // at login: it is there, dead, and respawn() reaches it.
  const enter = () => {
    {
      joined = true
      // (What a block was is read before it is dug: afterwards the game says air.) A dig says what came of it:
      // {dug: the block's name, at, tool: the item in the hand (null: the bare hand), seconds, gone: the block is
      // not there any more as the game has it now}.
      const dig = bot.dig.bind(bot)
      bot.dig = async (block, ...rest) => {
        const name = block && block.name
        const at = block && block.position
        const tool = bot.heldItem ? bot.heldItem.name : null
        const began = Date.now()
        await dig(block, ...rest)
        const using = doing('use')
        if (using && name) count(using.dug, name)
        const now = at && bot.blockAt(at)
        return { dug: name, at: pos(at), tool, seconds: +((Date.now() - began) / 1000).toFixed(2), gone: !now || now.name !== name }
      }
      // A placement says what came of it: {placed: the block's name as the game has it there now (null: nothing was
      // placed), at, seconds}.
      // (The head is turned to the face at once and the placement sent in the same tick: the library's own call
      // turns the head at its turning speed first, which takes longer than a jump lasts.)
      const placeBlock = (against, face) => bot._placeBlockWithOptions(against, face, { swingArm: 'right', forceLook: true })
      bot.placeBlock = async (against, face, ...rest) => {
        const at = against.position.plus(face)
        // A block goes only where the eyes could see the place it goes to, turning the head as they like: the
        // head need not be turned there, and the face it is put against need not show, but a place behind a
        // block (through a wall, past the edge of the floor the body stands on) takes none.
        if (!inSight(bot.blockAt(at, false))) {
          note('not_in_sight', { what: 'place at', name: bot.heldItem ? bot.heldItem.name : null, at: [at.x, at.y, at.z] })
          throw new Error(`not in sight: the place at (${at.x}, ${at.y}, ${at.z}) is behind a block; a block is placed only where the eyes could see the place it goes to`)
        }
        const began = Date.now()
        let error = null
        // Sneak is held down for the click, as a player places: a block put against a furnace, a chest or a door is
        // placed, not the furnace opened or the door turned. (The walk's steering keeps it down meanwhile: bot.placing.)
        bot.placing = (bot.placing || 0) + 1
        const sneaking = bot.getControlState('sneak')
        if (!sneaking) bot.setControlState('sneak', true)
        try { await placeBlock(against, face, ...rest) } catch (e) { error = e } finally {
          bot.placing--
          if (!sneaking && !bot.placing) bot.setControlState('sneak', false)
        }
        const now = bot.blockAt(at)
        const there = now && now.boundingBox === 'block' ? now.name : null
        if (error && !there) throw error
        return { placed: there, at: pos(at), seconds: +((Date.now() - began) / 1000).toFixed(2) }
      }
      // The body acts only on what it can see, as a player does: it digs, uses, opens and hits a block or an
      // entity only when a line from its eyes reaches it with no block in between. (The server
      // checks reach, not sight: without this the body dug ore, opened chests and hit mobs through walls.)
      // Else the call fails with 'not in sight'. What it knows of the world is not limited.
      const eye = () => bot.entity.position.offset(0, 1.62, 0)
      // What the eyes see: a block or an entity is in sight when some part of it shows, as on the screen. Every
      // side of its box turned to the eyes is looked at, a 5x5 grid of points over each, and a point shows when
      // the line from the eyes to it meets nothing before it (for a block: meets that block first). Only what has
      // a shape hides anything (grass, flowers and air do not). One test for everything: the body's acts, the
      // senses and the routines all ask bot.inSight. bot.inSight(target, from, through): from another point
      // of view, and as if the block at `through` were gone.
      const GRID = [0.02, 0.26, 0.5, 0.74, 0.98]
      const boxOf = (t) => {
        if (t.shapes !== undefined) {
          const at = t.position
          const shapes = t.shapes && t.shapes.length ? t.shapes : [[0, 0, 0, 1, 1, 1]]
          const lo = [1, 1, 1]; const hi = [0, 0, 0]
          for (const sh of shapes) for (let k = 0; k < 3; k++) { lo[k] = Math.min(lo[k], sh[k]); hi[k] = Math.max(hi[k], sh[k + 3]) }
          return { block: at, min: [at.x + lo[0], at.y + lo[1], at.z + lo[2]], max: [at.x + hi[0], at.y + hi[1], at.z + hi[2]], solid: !!(t.shapes && t.shapes.length) }
        }
        const w = (t.width || 0.6) / 2; const h = t.height || 1.8; const q = t.position
        return { block: null, min: [q.x - w, q.y, q.z - w], max: [q.x + w, q.y + h, q.z + w] }
      }
      const inSight = (t, from, through) => {
        if (!t || !t.position) return true
        if (t === bot.entity && !from) return true
        const e = from || eye(); const E = [e.x, e.y, e.z]; const box = boxOf(t)
        if ([0, 1, 2].every((k) => E[k] >= box.min[k] && E[k] <= box.max[k])) return true
        for (let k = 0; k < 3; k++) {
          const side = E[k] < box.min[k] ? box.min[k] : E[k] > box.max[k] ? box.max[k] : null
          if (side === null) continue
          const u = (k + 1) % 3; const v = (k + 2) % 3
          for (const a of GRID) {
            for (const b of GRID) {
              const pt = [0, 0, 0]
              pt[k] = side
              pt[u] = box.min[u] + (box.max[u] - box.min[u]) * a
              pt[v] = box.min[v] + (box.max[v] - box.min[v]) * b
              const to = new Vec3(pt[0], pt[1], pt[2]); const d = to.minus(e); const length = d.norm()
              if (length < 0.05) return true
              const hit = bot.world.raycast(e, d.scaled(1 / length), length + (box.block && box.solid ? 0.05 : 0))
              if (box.block && box.solid) { if (hit && hit.position.equals(box.block)) return true; continue }
              if (!hit || (hit.intersect && hit.intersect.distanceTo(e) >= length - 0.02)) return true
              if (through && hit.position.equals(through)) { const back = bot.world.raycast(to, d.scaled(-1 / length), length); if (!back || back.position.equals(through)) return true }
            }
          }
        }
        return false
      }
      const blockInSight = (block) => inSight(block)
      const entityInSight = (entity) => inSight(entity)
      bot.inSight = inSight
      bot.blockInSight = blockInSight
      // (Mineflayer's own bot.canSeeBlock casts one ray at the block's centre and says no where a side of the
      // block shows: it is the same test here, so that no two answers stand beside each other.)
      bot.canSeeBlock = blockInSight
      bot.entityInSight = entityInSight
      const where = (p) => p ? `${Math.floor(p.x)}, ${Math.floor(p.y)}, ${Math.floor(p.z)}` : '?'
      const unseen = (what, name, p) => {
        note('not_in_sight', { what, name, at: p ? [Math.floor(p.x), Math.floor(p.y), Math.floor(p.z)] : null })
        return new Error(`not in sight: ${name || 'it'} at (${where(p)}) is behind a block; ${what} only what the body can see`)
      }
      const blockActs = { dig: 'dig', activateBlock: 'use', openBlock: 'open', sleep: 'sleep in' }
      for (const [name, verb] of Object.entries(blockActs)) {
        const real = bot[name].bind(bot)
        bot[name] = async (block, ...rest) => {
          if (!blockInSight(block)) throw unseen(verb, block && block.name, block && block.position)
          return real(block, ...rest)
        }
      }
      const craft = bot.craft.bind(bot)
      bot.craft = async (recipe, count, table, ...rest) => {
        if (table && !blockInSight(table)) throw unseen('craft at', table.name, table.position)
        return craft(recipe, count, table, ...rest)
      }
      // Filling the bucket in the hand from the source given: when some point of the source is within 5 of the eyes
      // and the source is in sight by the one test of sight every act goes by (inSight: only what has a shape hides
      // anything), the server does what a filled bucket does, by its commands (rcon): the source becomes air, and the
      // empty bucket in the hand the filled one (of more than one, the filled one goes into the inventory).
      const REACH_BUCKET = 5
      const source = (b) => !!b && (b.name === 'water' || b.name === 'lava') && b.metadata === 0
      bot.fillBucket = async (block) => {
        if (!bot.heldItem || bot.heldItem.name !== 'bucket') throw new Error('fillBucket: the hand holds ' + (bot.heldItem ? bot.heldItem.name : 'nothing') + ', not an empty bucket')
        const now = block && block.position && bot.blockAt(block.position, false)
        if (!source(now)) throw new Error(`fillBucket: (${where(block && block.position)}) is ${now ? now.name + (now.metadata ? ' that flows' : '') : 'not loaded'}, not a source of water or lava`)
        const at = now.position; const from = eye(); const want = now.name + '_bucket'
        const points = []
        for (const y of [0.8, 0.5, 0.2]) for (const x of [0.5, 0.2, 0.8]) for (const z of [0.5, 0.2, 0.8]) points.push(at.offset(x, y, z))
        const near = points.filter(q => q.distanceTo(from) <= REACH_BUCKET).sort((a, b) => a.distanceTo(from) - b.distanceTo(from))
        if (!near.length) throw new Error(`fillBucket: the ${now.name} at (${where(at)}) is ${at.offset(0.5, 0.5, 0.5).distanceTo(from).toFixed(1)} from the eyes; a bucket reaches ${REACH_BUCKET}`)
        if (!inSight(now)) throw unseen('fill the bucket from', now.name, at)
        await bot.lookAt(near[0], true)   // (the head faces the source, as a player's does)
        const count = bot.heldItem.count; const me = bot.username; const cell = `${at.x} ${at.y} ${at.z}`
        const world = `execute in minecraft:${dimension().replace(/^minecraft:/, '')}`
        const took = await rcon(`${world} if block ${cell} minecraft:${now.name}[level=0] run setblock ${cell} minecraft:air`)
        if (!/^Changed the block/.test(took)) throw new Error(`fillBucket: the ${now.name} at (${where(at)}) was no longer a source; nothing was taken`)
        const gave = count === 1
          ? [await rcon(`replaceitem entity ${me} weapon.mainhand minecraft:${want}`)]
          : [await rcon(`replaceitem entity ${me} weapon.mainhand minecraft:bucket ${count - 1}`), await rcon(`give ${me} minecraft:${want}`)]
        if (!gave.every(answer => /^(Replaced a slot|Gave )/.test(answer))) {
          throw new Error(`fillBucket: the ${now.name} at (${where(at)}) was taken, and the bucket was not given: ${gave.join(' / ')}`)
        }
        // (What the server changed reaches the body with its next packets: the hand and the cell each in its own.)
        const filled = () => (count === 1 ? bot.heldItem && bot.heldItem.name === want : bot.heldItem && bot.heldItem.count === count - 1) &&
          !source(bot.blockAt(at, false))
        for (let k = 0; k < 40 && !filled(); k++) await sleep(25)
        return { item: want, from: [at.x, at.y, at.z] }
      }
      // Putting the liquid of the bucket in the hand into the cell `at`. A used full bucket puts it on the outer side
      // of the face that a line from the eyes the way the head faces meets first (BucketItem.use and emptyBucket in
      // the 1.16.1 server). So this is done as filling is: some point of the cell is within 5 of the eyes and the cell
      // is in sight by the one test of sight (inSight), and the server does there what the bucket does, by its commands: the cell takes the liquid when it is air, a liquid,
      // or a block the body walks through (that block is broken, and drops what breaking it drops); water in the
      // Nether is gone at once (the dimension is too warm); the hand holds an empty bucket.
      bot.pourBucket = async (target) => {
        const held = bot.heldItem && bot.heldItem.name
        if (held !== 'water_bucket' && held !== 'lava_bucket') throw new Error('pourBucket: the hand holds ' + (held || 'nothing') + ', not a water or lava bucket')
        const at = target && (target.position || target)
        if (!at || typeof at.x !== 'number') throw new Error('pourBucket: give the cell, as a Vec3 or a block')
        const cell = new Vec3(Math.floor(at.x), Math.floor(at.y), Math.floor(at.z))
        const now = bot.blockAt(cell, false)
        if (!now) throw new Error(`pourBucket: (${where(cell)}) is not loaded`)
        const liquid = held === 'water_bucket' ? 'water' : 'lava'
        const takes = /^(air|cave_air|void_air|water|lava)$/.test(now.name) || now.boundingBox === 'empty'
        if (!takes) throw new Error(`pourBucket: (${where(cell)}) is ${now.name}: liquid goes into air, a liquid or a block the body walks through`)
        const from = eye()
        const points = []
        for (const y of [0.5, 0.2, 0.8]) for (const x of [0.5, 0.2, 0.8]) for (const z of [0.5, 0.2, 0.8]) points.push(cell.offset(x, y, z))
        const near = points.filter(q => q.distanceTo(from) <= REACH_BUCKET).sort((a, b) => a.distanceTo(from) - b.distanceTo(from))
        if (!near.length) throw new Error(`pourBucket: (${where(cell)}) is ${cell.offset(0.5, 0.5, 0.5).distanceTo(from).toFixed(1)} from the eyes; a bucket reaches ${REACH_BUCKET}`)
        if (!inSight(now)) throw unseen('pour the bucket into', now.name, cell)
        await bot.lookAt(near[0], true)   // (the head faces the cell, as a player's does)
        const me = bot.username; const place = `${cell.x} ${cell.y} ${cell.z}`
        const world = `execute in minecraft:${dimension().replace(/^minecraft:/, '')}`
        const gone = liquid === 'water' && /nether/.test(dimension())
        if (!gone) {
          const put = await rcon(`${world} if block ${place} minecraft:${now.name} run setblock ${place} minecraft:${liquid} destroy`)
          // (A source of that liquid there already: the server changes nothing, and the bucket is emptied all the same.)
          const same = now.name === liquid && now.metadata === 0
          if (!/^Changed the block/.test(put) && !(same && /^Could not set the block/.test(put))) {
            throw new Error(`pourBucket: (${where(cell)}) changed in the moment between; nothing was poured`)
          }
        }
        const emptied = await rcon(`replaceitem entity ${me} weapon.mainhand minecraft:bucket`)
        if (!/^Replaced a slot/.test(emptied)) throw new Error(`pourBucket: the ${liquid} was poured at (${where(cell)}), and the bucket was not emptied: ${emptied}`)
        // (What the server changed reaches the body with its next packets: the hand and the cell each in its own.)
        const done = () => bot.heldItem && bot.heldItem.name === 'bucket' && (gone || (bot.blockAt(cell, false) || {}).name === liquid)
        for (let k = 0; k < 40 && !done(); k++) await sleep(25)
        return { item: 'bucket', into: [cell.x, cell.y, cell.z], liquid, ...(gone ? { evaporated: true } : {}) }
      }
      // (Placing a block asks for the place it goes to, not for the face it is put against: bot.placeBlock above.)
      const attack = bot.attack.bind(bot)
      bot.attack = (entity, ...rest) => {
        if (!entityInSight(entity)) throw unseen('hit', entity && entity.name, entity && entity.position)
        return attack(entity, ...rest)
      }
      for (const name of ['activateEntity', 'activateEntityAt', 'openEntity']) {
        const real = bot[name].bind(bot)
        bot[name] = async (entity, ...rest) => {
          if (!entityInSight(entity)) throw unseen('use', entity && entity.name, entity && entity.position)
          return real(entity, ...rest)
        }
      }
      // dig times and best tools as the server has them (see dig_rules.js)
      applyServerDigRules(bot.registry)
      registry = bot.registry
      nav = makeNav(bot, { note })
      for (const [kind, name, code] of navDefined.splice(0)) { try { nav.define(kind, name, code) } catch (error) { note('nav_load_error', { name, message: error.message }) } }
      // Items the body throws away: an item entity that appears within 4 of the body in the 1.5 s after its own toss is
      // marked for 5 min: bot.tossedItem(entity) says so (walking over it picks it up again).
      const tossed = new Map(); let lastToss = 0
      // An inventory click the server did not take is tried again, up to 2 more times, once the body's view is put
      // right. Rejected (the server's idea of a slot differs from ours, e.g. after a refused placement): the server
      // sends the inventory again, 0.4 s. Not answered (the click went to a window the server no longer has open): that
      // window is closed here too, so that the click goes to the inventory.
      for (const name of ['equip', 'unequip', 'moveSlotItem', 'toss', 'tossStack']) {
        if (typeof bot[name] !== 'function') continue
        const real = bot[name].bind(bot)
        bot[name] = async (...a) => { for (let k = 0; ; k++) { try { return await real(...a) } catch (e) {
          const text = String(e && e.message)
          const how = /Server rejected transaction/.test(text) ? 'rejected' : /Server didn't respond to transaction/.test(text) ? 'not answered' : null
          if (k >= 2 || !how) throw e
          note('click_rejected', { call: name, try: k + 1, how, window: bot.currentWindow ? bot.currentWindow.type : null })
          if (how === 'not answered' && bot.currentWindow) { try { await bot.closeWindow(bot.currentWindow) } catch (_) {} }
          await new Promise((resolve) => setTimeout(resolve, 400)) } } }
      }
      for (const name of ['toss', 'tossStack']) { const real = bot[name].bind(bot); bot[name] = (...a) => { lastToss = Date.now(); return real(...a).finally(() => { lastToss = Date.now() }) } }
      bot.on('entitySpawn', (e) => { if (e && e.name === 'item' && Date.now() - lastToss < 1500 && e.position.distanceTo(bot.entity.position) < 4) tossed.set(e.id, Date.now() + 300000) })
      bot.tossedItem = (e) => { const t = e && tossed.get(e.id); if (!t) return false; if (t < Date.now() || !bot.entities[e.id]) { tossed.delete(e.id); return false } return true }
      note('joined', { dimension: dimension() })
      send({ ev: 'ready' })
    }
  }
  bot.on('spawn', () => {
    if (!joined) enter()
    else note('respawn_or_dimension', { dimension: dimension() })
  })
  bot.on('messagestr', (message, where) => {
    const line = String(message).slice(0, 300)
    said.push({ t: Date.now(), line }); if (said.length > 20) said.shift()
    note('chat', { message: line, where })
  })
  // The game tells a player why they died (the line on the death screen): a message naming
  // the player, just before the death itself.
  bot.on('death', () => {
    if (!joined) return enter()   // (logged in dead: the death was told when it happened)
    const now = Date.now()
    const line = said.filter(s => now - s.t < 1500 && s.line.startsWith(bot.username + ' ')).pop()
    note('death', { position: pos(bot.entity.position), message: line ? line.line : null })
    // The server makes a new player at the respawn and tells nothing about what the dead one had: the window it had
    // open and its effects are gone there, so they are dropped from the body's picture here.
    if (bot.currentWindow) { const old = bot.currentWindow; bot.currentWindow = null; bot.emit('windowClose', old) }
    bot.entity.effects = {}
  })
  // A window (a chest, a furnace, a crafting table) opens and closes: said, with its kind.
  bot.on('windowOpen', (w) => note('window', { open: true, type: w ? w.type : null }))
  bot.on('windowClose', (w) => note('window', { open: false, type: w ? w.type : null }))
  bot.on('health', () => note('health', { health: bot.health, food: bot.food }))
  bot.on('entityHurt', (en) => { if (en === bot.entity) note('hurt', { health: bot.health }) })
  bot.on('kicked', (reason) => note('kicked', { reason: String(reason).slice(0, 300) }))
  bot.on('error', (error) => note('error', { message: String(error && error.message).slice(0, 300) }))
  bot.on('playerCollect', (collector) => { if (collector === bot.entity) note('collect', {}) })
  bot.on('physicsTick', () => { ticks++ })
  // Without the connection there is no body: this process ends and the bridge starts another.
  bot.on('end', (reason) => { note('end', { reason: String(reason) }); setTimeout(() => process.exit(3), 50) })
}

// ---------------------------------------------------------------- what the body reports

// How far it is down to the first solid block under the feet; null when there is none within 64.
function dropBelow () {
  const p = bot.entity.position
  const x = Math.floor(p.x); const z = Math.floor(p.z)
  for (let y = Math.floor(p.y) - 1; y >= Math.max(0, Math.floor(p.y) - 64); y--) {
    const block = bot.blockAt(new Vec3(x, y, z))
    if (!block) return null
    if (block.boundingBox === 'block') return +(p.y - (y + 1)).toFixed(1)
  }
  return null
}

function senseOnce (sense) {
  const value = sense.fn(bot, Vec3, helpers())
  if (value && typeof value.then === 'function') { if (typeof value.catch === 'function') value.catch(() => {}); throw new Error('it returned a promise: a sense does not wait') }
  return value
}

function loadSense (name, code) {
  const sense = senses[name] = { fn: new Function('bot', 'Vec3', 'h', code), slow: 0, error: null }
  sensesNow[name] = () => senseOnce(sense)
  return sense
}

// {values, errors}: every sense as it is now; a sense that failed is null, with why.
function sensed () {
  const values = {}; const errors = {}
  for (const name in senses) {
    const sense = senses[name]
    values[name] = null
    if (sense.slow < SENSE_SLOW) {
      const began = performance.now()
      try { values[name] = plain(senseOnce(sense)); sense.error = null } catch (error) { sense.error = String(error && error.message !== undefined ? error.message : error).slice(0, 200) }
      const took = performance.now() - began
      sense.slow = took > SENSE_MS ? sense.slow + 1 : 0
      if (sense.slow >= SENSE_SLOW) sense.error = `it took ${took.toFixed(0)} ms, more than the ${SENSE_MS} ms a sense has, ${SENSE_SLOW} times running: it is not computed until it is defined again`
    }
    if (sense.error) errors[name] = sense.error
  }
  return { values, errors }
}

function state () {
  if (!joined || !bot.entity) return { connected: false, ticks }
  const now = sensed()
  const items = {}
  for (const it of bot.inventory.items()) items[it.name] = (items[it.name] || 0) + it.count
  const near = []
  for (const id in bot.entities) {
    const en = bot.entities[id]
    if (en === bot.entity || !en.position) continue
    const d = en.position.distanceTo(bot.entity.position)
    // category: the game data's category of the kind (Mineflayer's entity.kind), as it is named there. It says nothing
    // of whether the entity attacks the body.
    if (d <= 48) near.push({ name: en.name || en.username || en.type, kind: en.type, category: en.kind || null, distance: +d.toFixed(1), position: pos(en.position) })
  }
  near.sort((a, b) => a.distance - b.distance)
  const held = bot.heldItem
  return {
    connected: true,
    ticks,
    position: pos(bot.entity.position),
    yaw: +bot.entity.yaw.toFixed(2),
    pitch: +bot.entity.pitch.toFixed(2),
    on_ground: bot.entity.onGround,
    velocity: pos(bot.entity.velocity),
    drop_below: dropBelow(),
    dimension: dimension(),
    health: bot.health,
    // The body died and has not been told to respawn.
    dead: bot.isAlive === false,
    food: bot.food,
    oxygen: bot.oxygenLevel,
    level: bot.experience ? bot.experience.level : 0,
    time_of_day: bot.time ? bot.time.timeOfDay : null,
    world_age_ticks: bot.time ? Number(bot.time.bigAge || bot.time.age) : null,
    raining: bot.isRaining,
    held: held ? held.name : null,
    armor: [5, 6, 7, 8, 45].map(i => bot.inventory.slots[i]).filter(Boolean).map(i => i.name),
    inventory: items,
    entities: near.slice(0, 30),
    sensed: now.values,
    sense_errors: now.errors,
    doing: doingNow()
  }
}

// ---------------------------------------------------------------- the game window
//
// A real game client can watch as this player: the bridge holds its connection and gives it
// every packet the server sends the bot (sent on from here, untouched). What a server
// never tells a player, because it is the player's own doing, is told from here: where the
// body is and looks, the hand it swings, the slot it holds, a window it closes.

const VIEW = process.env.VIEW === '1' || process.env.VIEW === 'again'
// 'again': the window has had a login on this connection already (this body follows one that was ended).
const VIEW_AGAIN = process.env.VIEW === 'again'
function view (name, params) { send({ ev: 'view', name, params }) }

function mirror () {
  const conv = require('mineflayer/lib/conversions')
  const client = bot._client
  // The bytes are taken where the client's own parser gets them from, and before it: a
  // parser may rewrite a packet in place while reading it (this one does), may fail on one,
  // or may not know one, and none of that may reach the window. Each is copied at once.
  const ids = require('minecraft-data')(VERSION).protocol.play.toClient.types.packet[1][0].type[1].mappings
  const keepAlive = Number(Object.keys(ids).find(id => ids[id] === 'keep_alive'))   // the bridge keeps the window alive itself
  const joinGame = Number(Object.keys(ids).find(id => ids[id] === 'login'))
  // The server ending the body's connection is not passed on: the window's connection is the
  // bridge's, and it follows the next body's login on it (a server stopped for a new world
  // had closed the window, which never came back).
  const kick = Number(Object.keys(ids).find(id => ids[id] === 'kick_disconnect'))
  const frame = (bytes) => {
    if (bytes[0] === keepAlive || bytes[0] === kick) return
    send({ ev: 'pkt', buf: Buffer.from(bytes) })
    // A game client that is given a second login on one connection shows its loading screen and
    // keeps it: it takes the screen down at the first position after a login or a respawn, and
    // only a respawn makes it wait for one again. So the login of a body that follows another is
    // followed by a respawn into the same world, built from that login, before anything else.
    if (VIEW_AGAIN && bytes[0] === joinGame) {
      try {
        const login = client.deserializer.parsePacketBuffer(Buffer.from(bytes)).data.params
        view('respawn', { dimension: login.dimension, worldName: login.worldName, hashedSeed: login.hashedSeed, gamemode: login.gameMode, previousGamemode: login.previousGameMode, isDebug: login.isDebug, isFlat: login.isFlat, copyMetadata: true })
      } catch (error) { note('error', { message: 'the window after a new login: ' + error.message }) }
    }
  }
  client.on('state', (now) => { if (now === 'play') (client.decompressor || client.splitter).prependListener('data', frame) })
  const write = client.write.bind(client)
  client.write = (name, params) => {
    if (name === 'held_item_slot') view('held_item_slot', { slot: params.slotId })
    else if (name === 'arm_animation') view('animation', { entityId: bot.entity ? bot.entity.id : 0, animation: params.hand ? 3 : 0 })
    else if (name === 'close_window') view('close_window', { windowId: params.windowId })
    return write(name, params)
  }
  let was = ''; let teleport = 1; let still = 0
  bot.on('physicsTick', () => {
    const e = bot.entity
    const now = { x: e.position.x, y: e.position.y, z: e.position.z, yaw: conv.toNotchianYaw(e.yaw), pitch: conv.toNotchianPitch(e.pitch) }
    const key = JSON.stringify(now)
    // Said again once a second while the body stands still: the window's own player moves
    // by the window's own input and physics, and is put back on the body.
    if (key === was && ++still < 20) return
    was = key; still = 0
    view('position', { ...now, flags: 0, teleportId: teleport++ })
  })
}

// The bridge answers for the body from what is pushed here, so it answers even while code
// keeps this process busy; that these stop coming is how it knows.
setInterval(() => {
  let now = { connected: false, ticks }
  try { now = state() } catch (error) { now = { connected: false, ticks, error: String(error && error.message) } }
  // What the code that runs asks to hold the body with now (h.priority): the name of a node of the tree (its place),
  // or true (above every node); null when no code asks.
  let asked = null
  for (const ctx of contexts.values()) if (!ctx.over && !ctx.paused && ctx.priority) { asked = ctx.priority; if (asked === true) break }
  now.priority = asked
  send({ ev: 'state', state: now })
}, 50)

// ---------------------------------------------------------------- running the caller's code
//
// Code has the body through a context of its own: the bot it is given is the Mineflayer bot
// behind a gate. The body has three channels: move (the movement keys), look (where the head
// turns) and use (the hand: dig, place, hit, use an item, the inventory and windows). Code
// says which it uses (its channels; none said: all of them), and acts only on those: two
// codes that run at once use channels of their own (the bridge pauses or ends the one that
// would share one). A context that is paused (code of a higher priority took its channels)
// keeps everything it has, and what it does to the body waits at the gate: an action it
// calls starts when it goes on, one that was under way (digging, looking, eating) is let go
// and done again then, and the keys it held and the item in its hand are put back. What it
// reads is never held. When code ends, the timers it set and the listeners it put on the bot
// end with it, its channels are let go (keys up, no dig, the item used no longer), and the
// actions the code still calls on its bot fail.

const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor
const TIMERS = ['setTimeout', 'setInterval', 'setImmediate', 'clearTimeout', 'clearInterval', 'clearImmediate']
function compile (code) {
  return new AsyncFunction('bot', 'h', 'Vec3', 'skills', 'sleep', 'log', 'signal', 'args', 'senses', ...TIMERS, code)
}

// Actions that take time: they wait at the gate.
const WAITS = new Set(['dig', 'placeBlock', 'placeEntity', 'equip', 'unequip', 'consume', 'craft', 'lookAt', 'look', 'activateBlock', 'activateEntity', 'activateEntityAt',
  'openContainer', 'openChest', 'openFurnace', 'openDispenser', 'openEnchantmentTable', 'openAnvil', 'openVillager', 'openBlock', 'openEntity', 'toss', 'tossStack', 'fish', 'sleep', 'wake', 'fillBucket', 'pourBucket',
  'clickWindow', 'transfer', 'moveSlotItem', 'putAway', 'putSelectedItemRange', 'trade', 'mount', 'elytraFly', 'waitForTicks', 'waitForChunksToLoad'])
// The calls of bot.creative: the ones that take time, and the ones that happen at once.
const CREATIVE_WAITS = new Set(['setInventorySlot', 'clearSlot', 'clearInventory', 'flyTo'])
const CREATIVE_ACTS = new Set(['startFlying', 'stopFlying'])
// Of those, the ones that go on for long: a pause lets them go, and they are done again afterwards.
const AGAIN = new Set(['dig', 'lookAt', 'look', 'consume', 'fish', 'waitForTicks'])
// Actions that happen at once: a paused context's are not done (the keys it sets are kept for later).
const ACTS = new Set(['setControlState', 'clearControlStates', 'attack', 'swingArm', 'activateItem', 'deactivateItem', 'setQuickBarSlot', 'chat', 'whisper', 'dismount', 'closeWindow', 'stopDigging', 'updateHeldItem'])
const LISTENS = new Set(['on', 'once', 'addListener', 'prependListener', 'prependOnceListener'])
// The channels each action uses (one not named here uses none: chat, waiting for ticks).
const CHANNELS = ['move', 'look', 'use']
const USES = {}
for (const name of ['setControlState', 'clearControlStates']) USES[name] = ['move']
for (const name of ['look', 'lookAt']) USES[name] = ['look']
for (const name of ['equip', 'unequip', 'consume', 'craft', 'toss', 'tossStack', 'fish', 'sleep', 'wake', 'clickWindow',
  'transfer', 'moveSlotItem', 'putAway', 'putSelectedItemRange', 'trade', 'mount', 'dismount', 'elytraFly', 'attack', 'swingArm',
  'activateItem', 'deactivateItem', 'setQuickBarSlot', 'closeWindow', 'stopDigging', 'updateHeldItem', 'openContainer',
  'openChest', 'openFurnace', 'openDispenser', 'openEnchantmentTable', 'openAnvil', 'openVillager', 'openEntity']) USES[name] = ['use']
// (These turn the head to what they act on.)
for (const name of ['dig', 'placeBlock', 'placeEntity', 'activateBlock', 'activateEntity', 'activateEntityAt', 'openBlock', 'fillBucket', 'pourBucket']) USES[name] = ['use', 'look']
for (const name of [...CREATIVE_WAITS, ...CREATIVE_ACTS]) USES['creative.' + name] = name === 'flyTo' ? ['move'] : ['use']
// The context that runs now and uses `channel`; null when none does.
function holder (channel) {
  for (const ctx of contexts.values()) if (!ctx.over && !ctx.paused && (!ctx.channels || ctx.channels.includes(channel))) return ctx
  return null
}
// An action on a channel the code did not say it uses fails.
function mayUse (ctx, name) {
  const need = USES[name]
  if (!need || !ctx.channels) return
  const missing = need.filter(channel => !ctx.channels.includes(channel))
  if (missing.length) throw new Error(`${name.replace('creative.', 'creative ')} uses the channel ${missing.join(' and ')}: this code said it uses ${ctx.channels.join(', ')}`)
}

const compiled = {}          // routine name -> its compiled code
const contexts = new Map()   // id -> the context of code that has not ended (running or paused)
const HEARD_MS = 200         // by then the run has read a state the body sent after a change

function defer () { let resolve; const promise = new Promise(r => { resolve = r }); return { promise, resolve } }

// null when the context may act now; a promise that resolves when it may; throws when it never will.
// Code that was told to stop waits for nothing more on the body: what it waits for fails
// with 'stopped', at once, and so does what it then asks the body to wait for.
function gate (ctx) {
  if (ctx.over) throw new Error('this code has ended: it no longer has the body')
  if (ctx.stop) throw new Error('stopped')
  if (!ctx.paused) return null
  return new Promise((resolve, reject) => ctx.waiting.push({ resolve, reject }))
}

function free (ctx) {
  const gone = ctx.over || (ctx.stop && ctx.paused)
  for (const one of ctx.waiting.splice(0)) gone ? one.reject(new Error('stopped')) : one.resolve()
}

function waits (ctx, target, name, fn) {
  return async (...args) => {
    mayUse(ctx, name)
    for (;;) {
      const wait = gate(ctx); if (wait) await wait
      const epoch = ctx.epoch
      const real = Promise.resolve().then(() => fn.apply(target, args))
      const out = await Promise.race([real.then(value => ({ value }), error => ({ error })),
        ctx.stopping.promise.then(() => ({ stopped: true })),
        ...(AGAIN.has(name) ? [ctx.pausing.promise.then(() => ({ paused: true }))] : [])])
      if (out.stopped || ctx.stop) throw new Error('stopped')
      if (out.paused || (AGAIN.has(name) && out.error && ctx.epoch !== epoch && !ctx.over)) continue
      if (out.error) throw out.error
      return out.value
    }
  }
}

function acts (ctx, target, name, fn) {
  return (...args) => {
    if (ctx.over) throw new Error('this code has ended: it no longer has the body')
    mayUse(ctx, name)
    if (name === 'setControlState') ctx.controls[args[0]] = !!args[1]
    else if (name === 'clearControlStates') ctx.controls = {}
    if (ctx.paused) return undefined
    return fn.apply(target, args)
  }
}

function wrap (ctx, target, special, waiting = WAITS, acting = ACTS, prefix = '') {
  const made = new Map()
  return new Proxy(target, {
    get (to, key) {
      const own = special(key)
      if (own !== undefined) return own
      const value = to[key]
      if (typeof value !== 'function') return value
      const had = made.get(key)
      if (had && had.of === value) return had.fn
      // (Every other function reads, and goes on working after the code ended.)
      const fn = waiting.has(key) ? waits(ctx, to, prefix + key, value) : acting.has(key) ? acts(ctx, to, prefix + key, value) : value.bind(to)
      made.set(key, { of: value, fn })
      return fn
    },
    set (to, key, value) { to[key] = value; return true }
  })
}

function context (id, send, channels) {
  const ctx = { id, stop: false, paused: false, over: false, epoch: 0, waiting: [], pausing: defer(), stopping: defer(), timers: new Map(), sleeps: new Set(), listeners: [], controls: {}, held: null,
    // (null: all three; []: none, for code that only puts rules of the walking in force.)
    channels: Array.isArray(channels) ? channels.filter(c => CHANNELS.includes(c)) : null,
    did: { dug: {}, placed: {}, broke: [], moved: 0, pulled_back: 0 } }
  // What the code can ask of itself: whether it was told to stop, and the times it was
  // paused so far ({by: who took the body, seconds; null while that pause lasts}).
  ctx.pauses = []
  // What the code expected (h.expect): {text, held, found} each, for its report.
  ctx.expects = []
  ctx.signal = { get stopped () { return ctx.stop }, get pauses () { return ctx.pauses.map(one => ({ by: one.by, seconds: one.seconds })) } }
  ctx.log = send
  // (timers: each with what ends it)
  const timer = (set, unset) => (fn, ...rest) => { if (ctx.over) throw new Error('this code has ended: it no longer has the body'); const t = set((...more) => { if (set !== setInterval) ctx.timers.delete(t); return fn(...more) }, ...rest); ctx.timers.set(t, unset); return t }
  const clear = (unset) => (t) => { ctx.timers.delete(t); unset(t) }
  ctx.timerFns = [timer(setTimeout, clearTimeout), timer(setInterval, clearInterval), timer(setImmediate, clearImmediate), clear(clearTimeout), clear(clearInterval), clear(clearImmediate)]
  ctx.sleep = (ms) => ctx.over ? Promise.reject(new Error('this code has ended: it no longer has the body')) : Promise.race([new Promise(resolve => { const t = setTimeout(() => { ctx.sleeps.delete(t); resolve() }, ms); ctx.sleeps.add(t) }),
    ctx.stopping.promise]).then(() => gate(ctx))
  const creative = bot.creative ? wrap(ctx, bot.creative, () => undefined, CREATIVE_WAITS, CREATIVE_ACTS, 'creative.') : undefined
  ctx.bot = wrap(ctx, bot, (key) => {
    if (key === 'creative' && creative) return creative
    if (key === 'pathfinder') return undefined   // (the search the body's own walking uses is not the caller's)
    if (LISTENS.has(key)) return (event, fn) => { ctx.listeners.push([event, fn]); bot[key](event, fn); return ctx.bot }
    return undefined
  })
  ctx.skills = routinesFor(ctx)
  // One action of the code holds the body with a priority: a reflex whose place is below
  // it waits until the action is over. The run hears of it with the body's state, so the
  // action begins once that has had time to arrive (the state goes out every 50 ms and the
  // run reads it at each of its steps).
  ctx.priority = null
  // h.priority(node, fn) or h.priority(fn): `node` the name of a node of the tree; without one, above every node.
  const during = async (node, fn) => {
    if (typeof node === 'function') { fn = node; node = true }
    const before = ctx.priority
    ctx.priority = typeof node === 'string' && node ? node : true
    try { await ctx.sleep(HEARD_MS); return await fn() } finally { ctx.priority = before }
  }
  // h.atomic(fn, seconds = 5): a step that must not be interrupted. No node takes the body while fn runs (as
  // h.priority(fn)); a pause asked meanwhile (by a run that had not yet heard of it) is made when fn is over. Past
  // `seconds` the step fails, and a pause asked meanwhile goes through then. Within a step, another h.atomic is
  // that same step.
  ctx.atomic = null
  const atomic = async (fn, seconds = 5) => {
    if (ctx.atomic) return fn()
    return during(true, async () => {
      ctx.atomic = { pending: null }
      let timer
      try {
        return await Promise.race([Promise.resolve().then(fn), new Promise((resolve, reject) => {
          timer = setTimeout(() => reject(new Error(`atomic: the step took longer than ${seconds} s`)), seconds * 1000)
        })])
      } finally {
        clearTimeout(timer)
        const pending = ctx.atomic.pending
        ctx.atomic = null
        if (pending) pause(ctx.id, pending.by)
      }
    })
  }
  // What the code relies on, checked where it is called: `check` returns true, or what it
  // found instead; then the code ends there, with what was found as its error.
  const expect = async (text, check) => {
    let found
    try { found = await check() } catch (error) {
      if (error && error.message === 'stopped') throw error
      found = 'the check threw ' + String(error && error.message)
    }
    if (found === true) { ctx.expects.push({ text: String(text), held: true }); ctx.log('expected "' + text + '": it held'); return true }
    let said
    try { said = typeof found === 'string' ? found : JSON.stringify(plain(found)) } catch (error) { said = String(found) }
    ctx.expects.push({ text: String(text), held: false, found: String(said).slice(0, 2000) })
    throw new Error('Nothing further ran: you expected "' + text + '". It does not hold: ' + String(said).slice(0, 2000))
  }
  // Walking (nav.js). h.go(goal, options) walks the body to the goal and resolves with what came of it; the walk
  // is this code's: it waits while the code is paused and ends when the code ends. h.path(goal, options) searches
  // the route and does not walk. h.avoid(name, args) puts a hazard or a route rule in force for as long as this code
  // lasts (or until h.unavoid(name)).
  const has = (channel) => !ctx.channels || ctx.channels.includes(channel)
  const go = async (goal, options) => {
    if (ctx.over) throw new Error('this code has ended: it no longer has the body')
    if (!has('move') || !has('look')) throw new Error('go uses the channels move and look: this code said it uses ' + ctx.channels.join(', '))
    const wait = gate(ctx); if (wait) await wait
    const usable = has('use')
    const walk = nav.go(goal, { ...(options || {}), ...(usable ? {} : { dig: false, place: false }) },
      { stopped: () => ctx.stop || ctx.over, paused: () => ctx.paused })
    ctx.walk = walk
    try { return await walk.done } finally { if (ctx.walk === walk) ctx.walk = null }
  }
  const route = (goal, options) => nav.path(goal, options || {}, () => !ctx.over && !ctx.stop)
  const avoid = (name, args) => { if (ctx.over) throw new Error('this code has ended'); nav.avoid(String(name), args, ctx.id) }
  const unavoid = (name) => nav.unavoid(String(name), ctx.id)
  // h.hold(): waits until this code is told to stop, and returns then (for code that keeps a rule in force).
  const hold = () => ctx.stopping.promise
  ctx.h = { Vec3, skills: ctx.skills, sleep: ctx.sleep, registry, priority: during, atomic, expect, channels: ctx.channels || CHANNELS, go, path: route, avoid, unavoid, hold, rules: () => nav.listed(), note: (kind, data) => note('user:' + kind, data || {}) }
  return ctx
}

// The saved routines as a context calls them: with that context's bot, sleep and timers.
function routinesFor (ctx) {
  return new Proxy({}, {
    get (to, name) {
      const fn = compiled[name]
      return fn && ((args = {}, log = ctx.log || (() => {}), signal = ctx.signal || { stopped: false }) =>
        fn(ctx.bot, ctx.h, Vec3, ctx.skills, ctx.sleep, log, signal, args, sensesNow, ...ctx.timerFns))
    },
    has (to, name) { return name in compiled },
    ownKeys () { return Object.keys(compiled) },
    getOwnPropertyDescriptor (to, name) { return name in compiled ? { enumerable: true, configurable: true, value: this.get(to, name) } : undefined }
  })
}

// (What a sense is given: it reads, so it has the bot as it is and no gate.)
const bare = { get bot () { return bot }, sleep, log: null, signal: null, timerFns: [setTimeout, setInterval, setImmediate, clearTimeout, clearInterval, clearImmediate] }
bare.skills = routinesFor(bare)
Object.defineProperty(bare, 'h', { get () { return helpers() } })
const skills = bare.skills
function helpers () { return { Vec3, skills, sleep, registry, note: (kind, data) => note('user:' + kind, data || {}) } }

function plain (value, depth = 0) {
  if (value === undefined) return null
  if (value === null || typeof value === 'number' || typeof value === 'boolean') return value
  if (typeof value === 'string') return value.length > 4000 ? value.slice(0, 4000) + '...' : value
  if (typeof value === 'bigint') return Number(value)
  if (typeof value === 'function') return '[function]'
  if (depth > 5) return '[deep]'
  if (value instanceof Vec3) return pos(value)
  if (value instanceof Error) return { error: value.message }
  if (Array.isArray(value)) return value.slice(0, 200).map(v => plain(v, depth + 1))
  if (typeof value === 'object') {
    if (value.position && value.name && value.stateId !== undefined) return { block: value.name, position: pos(value.position) }
    if (value.position && (value.type || value.username)) return { entity: value.name || value.username, kind: value.type, position: pos(value.position), health: value.health }
    if (value.count !== undefined && value.name && value.slot !== undefined) return { item: value.name, count: value.count, slot: value.slot }
    const out = {}
    let n = 0
    for (const key of Object.keys(value)) { if (n++ > 60) break; out[key] = plain(value[key], depth + 1) }
    return out
  }
  return String(value)
}

function loadSkill (name, code) { compiled[name] = compile(code) }

// What the code did on its channels is let go: the keys go up (move), the dig stops and the item is used no longer (use).
function letGo (ctx) {
  const has = (channel) => !ctx || !ctx.channels || ctx.channels.includes(channel)
  try { if (has('move')) bot.clearControlStates() } catch (error) {}
  try { if (has('use')) { bot.stopDigging(); bot.deactivateItem() } } catch (error) {}
}

function run (message) {
  const id = message.id
  if (!joined) return send({ ev: 'job', id, status: 'error', result: null, error: 'the body is not in the world', did: null })
  if (bot.isAlive === false) return send({ ev: 'job', id, status: 'error', result: null, error: 'the body is dead: no code runs on it until respawn()', did: null })
  let fn
  try { fn = compile(String(message.code)) } catch (error) { return send({ ev: 'job', id, status: 'error', result: null, error: 'syntax: ' + error.message, did: null }) }
  const log = (...parts) => send({ ev: 'log', id, line: parts.map(p => typeof p === 'string' ? p : JSON.stringify(plain(p))).join(' ').slice(0, 2000) })
  const ctx = context(id, log, message.channels)
  contexts.set(id, ctx)
  const done = ctx.done = (status, result, error) => {
    if (ctx.over) return
    ctx.over = true
    // What the code left behind ends with it, and its report says how much that was.
    const left = { timers: ctx.timers.size, listeners: 0 }
    for (const [t, unset] of ctx.timers) unset(t)
    for (const t of ctx.sleeps) clearTimeout(t)
    for (const [event, listener] of ctx.listeners) {
      if (bot.listeners(event).includes(listener)) { left.listeners++; bot.removeListener(event, listener) }
    }
    free(ctx)
    contexts.delete(id)
    // Its walk ends with it, and the hazards and route rules it put in force go.
    if (ctx.walk) ctx.walk.stop('the code ended')
    if (nav) nav.dropOwner(id)
    const what = summary(ctx.did)
    // Its channels are let go: the keys the code held go up, its dig stops.
    if (!ctx.paused) letGo(ctx)
    send({ ev: 'job', id, status, result, error, did: what, left, expected: ctx.expects })
  }
  Promise.resolve()
    .then(() => fn(ctx.bot, ctx.h, Vec3, ctx.skills, ctx.sleep, log, ctx.signal, message.args || {}, sensesNow, ...ctx.timerFns))
    .then(value => { let out; try { out = plain(value) } catch (error) { out = '[the value could not be read: ' + String(error && error.message).slice(0, 200) + ']' } done('done', out, null) },
      error => done('error', null, String(error && (error.stack || error.message || error)).split('\n').slice(0, 6).join('\n')))
}

// Code of a higher priority takes the body: this context keeps what it has and waits.
// The bridge hears that it is paused (send 'paused'), so that a pause is answered only once it is made.
function pause (id, by) {
  const ctx = contexts.get(id)
  if (!ctx || ctx.paused || ctx.over) return send({ ev: 'paused', id })
  // (A step that must not be interrupted runs: the pause is made when it is over, h.atomic.)
  if (ctx.atomic) { ctx.atomic.pending = { by: by || null }; return }
  ctx.paused = true; ctx.epoch++
  ctx.pauses.push({ by: by || null, seconds: null, at: Date.now() })
  ctx.held = bot.heldItem ? bot.heldItem.name : null
  ctx.pausing.resolve()
  letGo(ctx)
  send({ ev: 'paused', id })
}

// It has its channels again: the item it held and the keys it held are put back, and it goes on.
async function resume (id) {
  const ctx = contexts.get(id)
  if (ctx && ctx.atomic && ctx.atomic.pending) { ctx.atomic.pending = null; return }   // (a pause not yet made)
  if (!ctx || !ctx.paused || ctx.over) return
  const has = (channel) => !ctx.channels || ctx.channels.includes(channel)
  if (has('use') && ctx.held && (!bot.heldItem || bot.heldItem.name !== ctx.held)) {
    const item = bot.inventory.items().find(it => it.name === ctx.held)
    if (item) { try { await bot.equip(item, 'hand') } catch (error) {} }
  }
  if (!ctx.paused || ctx.over) return
  ctx.paused = false; ctx.pausing = defer()
  const last = ctx.pauses[ctx.pauses.length - 1]
  if (last && last.seconds === null) { last.seconds = +((Date.now() - last.at) / 1000).toFixed(2); delete last.at }
  try {
    if (has('move')) for (const key of Object.keys(ctx.controls)) if (ctx.controls[key]) bot.setControlState(key, true)
  } catch (error) {}
  free(ctx)
}

function stop (id) {
  const ctx = contexts.get(id)
  if (!ctx) return
  ctx.stop = true
  ctx.stopping.resolve()
  if (!ctx.paused) letGo(ctx)
  // Code that is paused has nothing to return to: it is over here and now, and what it
  // still tries on the body fails.
  else ctx.done('stopped', null, 'stopped while it was paused')
}

process.on('message', (message) => {
  if (message.op === 'run') run(message)
  else if (message.op === 'stop') stop(message.id)
  else if (message.op === 'pause') pause(message.id, message.by)
  else if (message.op === 'resume') resume(message.id)
  else if (message.op === 'load') { try { loadSkill(message.name, message.code) } catch (error) { note('skill_load_error', { name: message.name, message: error.message }) } }
  else if (message.op === 'unload') delete compiled[message.name]
  else if (message.op === 'nav') {
    // Hazards and route rules: defined, removed, put in force (by nobody's code: until taken out), taken out, listed.
    const answer = { ev: 'sense', ask: message.ask, ok: true, error: null }
    try {
      if (message.what === 'define') { if (nav) nav.define(message.kind, message.name, message.code); else { new Function(message.code); navDefined.push([message.kind, message.name, message.code]) } }
      else if (!nav) throw new Error('the body is not in the world')
      else if (message.what === 'undefine') nav.undefine(message.kind, message.name)
      else if (message.what === 'avoid') nav.avoid(message.name, message.args, null)
      else if (message.what === 'unavoid') answer.removed = nav.unavoid(message.name)
      if (nav) answer.listed = nav.listed()
    } catch (error) { answer.ok = false; answer.error = String(error && error.message).slice(0, 300) }
    send(answer)
  }
  else if (message.op === 'sense') {
    // Defined, and computed once at once: the answer says what it gives now.
    const answer = { ev: 'sense', ask: message.ask, defined: false, value: null, error: null }
    try {
      const sense = loadSense(message.name, message.code)
      answer.defined = true
      if (joined && bot.entity) { try { answer.value = plain(senseOnce(sense)) } catch (error) { answer.error = String(error && error.message !== undefined ? error.message : error).slice(0, 200) } } else answer.error = 'the body is not in the world'
    } catch (error) { answer.error = 'syntax: ' + error.message }
    send(answer)
  } else if (message.op === 'unsense') { delete senses[message.name]; delete sensesNow[message.name]; send({ ev: 'sense', ask: message.ask, removed: true }) }
  else if (message.op === 'respawn') { try { if (bot.isAlive === false) bot.respawn() } catch (error) { note('error', { message: 'respawn: ' + error.message }) } }
  else if (message.op === 'chat') { try { bot.chat(String(message.text).slice(0, 250)) } catch (error) { note('error', { message: 'chat: ' + error.message }) } }
})
process.on('disconnect', () => process.exit(0))   // the bridge is gone
process.on('uncaughtException', (error) => note('uncaught', { message: String(error && error.message).slice(0, 300) }))
process.on('unhandledRejection', (error) => note('unhandled', { message: String(error && error.message).slice(0, 300) }))

for (const file of fs.existsSync(path.join(STORE, 'skills')) ? fs.readdirSync(path.join(STORE, 'skills')) : []) {
  if (!file.endsWith('.js')) continue
  try { loadSkill(file.slice(0, -3), fs.readFileSync(path.join(STORE, 'skills', file), 'utf8')) } catch (error) { note('skill_load_error', { name: file, message: error.message }) }
}
for (const file of fs.existsSync(path.join(STORE, 'senses')) ? fs.readdirSync(path.join(STORE, 'senses')) : []) {
  if (!file.endsWith('.js')) continue
  try { loadSense(file.slice(0, -3), fs.readFileSync(path.join(STORE, 'senses', file), 'utf8')) } catch (error) { note('sense_load_error', { name: file, message: error.message }) }
}
for (const file of fs.existsSync(path.join(STORE, 'nav')) ? fs.readdirSync(path.join(STORE, 'nav')) : []) {
  const found = /^(hazard|rule)-(.+)\.js$/.exec(file)
  if (found) navDefined.push([found[1], found[2], fs.readFileSync(path.join(STORE, 'nav', file), 'utf8')])
}
connect()
