// A Mineflayer body behind a local HTTP port.
//
// This process keeps the port, the saved routines, the list of what happened and the jobs
// that run on the body. The body itself (the bot and the code that runs on it) is another
// process, body.js: the caller's code gets the Mineflayer bot there. The body has three
// channels (move, look, use); a job says which it uses (none said: all). Jobs that use
// channels of their own run at once; a new one ends a running job that uses one of its
// channels, unless that one was paused first (/pause): a paused job keeps what it has and
// goes on when it is resumed.
//
// Code always ends. Told to stop (its time is over, another job, /stop, the body died) it has GRACE_MS to
// return. When it does not, or when the body's process stops answering (code that never
// pauses) or its physics stop, the process is ended and started again: the body logs back
// in where it stood, with nothing of the old code left in memory (listeners, timers,
// variables); the saved routines are on disk and are loaded again. That is the only way
// code is ended by force, and it is reported as the event body_restarted.
//
// Nothing here knows how to play: there is no game strategy, recipe or route in this file.

const http = require('http')
const fs = require('fs')
const path = require('path')
const { fork } = require('child_process')
const mc = require('minecraft-protocol')

const BRIDGE_PORT = Number(process.env.BRIDGE_PORT || 8791)
const STORE = path.resolve(process.env.BRIDGE_STORE || path.join(__dirname, 'store'))
const GRACE_MS = Number(process.env.GRACE_MS || 3000)         // for code to return once told to stop
const SILENT_MS = Number(process.env.SILENT_MS || 5000)       // the body's process says nothing: its code never pauses
const STILL_MS = Number(process.env.STILL_MS || 8000)         // the body is in the world and its physics do not tick
const JOIN_MS = Number(process.env.JOIN_MS || 60000)          // for a new body process to be in the world
const VIEW_PORT = Number(process.env.VIEW_PORT || 0)          // a game client may watch as the body on this port
const VERSION = process.env.MC_VERSION || '1.16.1'
// The libraries are installed beside this package, not into it (an installed package is never written to):
// NODE_PATH names where; in a folder with its own node_modules, there.
const MODULES = (process.env.NODE_PATH || '').split(path.delimiter).filter(Boolean)[0] || path.join(__dirname, 'node_modules')

fs.mkdirSync(path.join(STORE, 'skills'), { recursive: true })
fs.mkdirSync(path.join(STORE, 'history'), { recursive: true })
fs.mkdirSync(path.join(STORE, 'senses'), { recursive: true })
fs.mkdirSync(path.join(STORE, 'nav'), { recursive: true })

const started = Date.now()
const events = []            // {seq, t, kind, ...}, a ring
let eventSeq = 0
const jobs = new Map()       // id -> job
let jobSeq = 0
const running = []           // the jobs that run on the body now, each on channels of its own
const paused = []            // the jobs that wait to have their channels again, the last paused last
const ALL = ['move', 'look', 'use']
const channelsOf = (job) => job.channels || ALL
const shares = (a, b) => channelsOf(a).some(channel => channelsOf(b).includes(channel))
let deaths = 0
let restarts = 0

let child = null
let ready = false            // the body is in the world
let lastHeard = 0            // when the body's process last said anything
let lastState = null         // what the body last reported of itself
let lastTicks = -1; let tickedAt = 0
let waiters = []             // resolvers waiting for the body to be in the world
const asked = new Map()      // what the body was asked and has not answered: number -> resolver
let askSeq = 0

function sleep (ms) { return new Promise(resolve => setTimeout(resolve, ms)) }

const EVENTS_LOG = process.env.BRIDGE_EVENTS_LOG || null   // everything that happens to the body, kept (but for its vital signs)
const UNKEPT = new Set(['health', 'hurt', 'collect'])

const awaited = new Set()   // those who wait for an event (GET /events with wait_seconds)

function note (kind, data = {}) {
  const last = events[events.length - 1]
  // The same thing over and over (a server that is down) is one line with a count.
  if (last && last.kind === kind && kind === 'body_gone' && last.why === data.why) { last.times = (last.times || 1) + 1; last.t = Date.now(); return }
  const event = { seq: ++eventSeq, t: Date.now(), kind, ...data }
  events.push(event)
  for (const heard of [...awaited]) heard()   // (whoever waits for an event hears of it now)
  if (events.length > 2000) events.splice(0, events.length - 2000)
  if (EVENTS_LOG && !UNKEPT.has(kind)) { try { fs.appendFileSync(EVENTS_LOG, JSON.stringify(event) + '\n') } catch (error) {} }
}

// ---------------------------------------------------------------- the body's process

// ---------------------------------------------------------------- the game window
//
// With VIEW_PORT set, a real game client joins this port and watches as the body itself: it
// is given every packet the server sends the bot, from the bot's login on, and what it
// sends is dropped. So it has to be here before the body logs in: the first body process
// waits for it, and a later one (after a restart) starts a new login the window follows on
// the same connection. A window that comes late is not on the body until then, and says so.

let viewer = null            // the game client's connection
let attached = false         // it has had everything since the body's login
let viewerSaid = null        // where the client last said its player is: {x, y, z, t}
let everStarted = false      // a body process has been started
let viewerHadLogin = false   // the game client was given a body's login on its connection

if (VIEW_PORT) {
  const server = mc.createServer({ host: '127.0.0.1', port: VIEW_PORT, 'online-mode': false, version: VERSION, maxPlayers: 1, motd: 'the body' })
  server.on('login', (client) => {
    if (viewer) { try { viewer.end('another window took the view') } catch (error) {} }
    viewer = client; attached = false; viewerSaid = null; viewerHadLogin = false
    note('window_joined', { name: client.username })
    const said = (packet) => { viewerSaid = { x: packet.x, y: packet.y, z: packet.z, t: Date.now() } }
    client.on('position', said)
    client.on('position_look', said)
    client.on('error', (error) => note('window_error', { message: String(error && error.message).slice(0, 200) }))
    client.on('end', (reason) => { if (viewer === client) { viewer = null; attached = false; note('window_left', { reason: String(reason) }) } })
    if (!everStarted) startBody()   // the first body waited for the window
  })
  server.on('error', (error) => note('bridge_error', { message: 'view port: ' + String(error && error.message) }))
}

function toViewer (send) {
  if (!viewer || !attached) return
  try { send(viewer) } catch (error) { note('bridge_error', { message: 'to the window: ' + String(error && error.message).slice(0, 200) }) }
}

// Whether a game server answers on the port the body logs in at.
function serverAnswers (done) {
  const socket = require('net').connect({ host: process.env.MC_HOST || '127.0.0.1', port: Number(process.env.MC_PORT || 25565) })
  let over = false
  const end = (up) => { if (over) return; over = true; socket.destroy(); done(up) }
  socket.once('connect', () => end(true)); socket.once('error', () => end(false)); socket.setTimeout(1000, () => end(false))
}

let waitingForServer = false
function startBody () {
  // Nothing is in the world yet: the window comes first (it cannot catch up later).
  if (VIEW_PORT && !viewer && !everStarted) return
  // No game server answers (a run that has not begun its first world, or a server that is being started on
  // another one): the body waits for one, since a process started now could only fail to log in.
  if (waitingForServer || child) return
  waitingForServer = true
  serverAnswers((up) => {
    waitingForServer = false
    if (!up) return setTimeout(startBody, 1000)
    launchBody()
  })
}

function launchBody () {
  everStarted = true
  ready = false; lastState = null; lastTicks = -1
  lastHeard = tickedAt = Date.now()
  attached = !!viewer
  const mine = child = fork(path.join(__dirname, 'body.js'), [], { env: { ...process.env, BRIDGE_STORE: STORE, VIEW: VIEW_PORT ? (attached && viewerHadLogin ? 'again' : '1') : '0' }, serialization: 'advanced', stdio: ['ignore', 'inherit', 'inherit', 'ipc'], windowsHide: true })   // (no console window of its own)
  mine.born = Date.now()
  if (attached) viewerHadLogin = true   // (the next body's login is this window's second)
  mine.on('message', (message) => { if (child === mine) heard(message) })
  mine.on('exit', (code, signal) => { if (child === mine) bodyGone(`the body's process ended (${signal || code})`) })
}

function heard (message) {
  lastHeard = Date.now()
  if (message.ev === 'pkt') return toViewer(client => client.writeRaw(Buffer.from(message.buf)))
  if (message.ev === 'view') return toViewer(client => client.write(message.name, message.params))
  if (message.ev === 'state') {
    lastState = message.state
    if (message.state.ticks !== lastTicks) { lastTicks = message.state.ticks; tickedAt = lastHeard }
  } else if (message.ev === 'ready') {
    ready = true; tickedAt = lastHeard
    for (const resolve of waiters.splice(0)) resolve(true)
  } else if (message.ev === 'event') {
    const { ev, kind, ...data } = message
    note(kind, data)
    if (kind === 'death') {
      deaths++
      // The body is dead, and comes back at its spawn point: where the code on it was acting
      // is gone, so that code ends with the body's death.
      for (const job of [...running, ...paused]) end(job, 'death')
    }
  } else if (message.ev === 'paused') {
    const made = pausing.get(message.id)
    if (made) { pausing.delete(message.id); made() }
  } else if (message.ev === 'sense') {
    const answer = asked.get(message.ask)
    if (answer) { asked.delete(message.ask); answer(message) }
  } else if (message.ev === 'log') {
    const job = jobs.get(message.id)
    if (job) { job.logs.push(message.line); if (job.logs.length > 400) job.logs.splice(0, 100) }
  } else if (message.ev === 'job') {
    const job = jobs.get(message.id)
    // (Code that was told to stop and let that error out was stopped: it did not fail.)
    if (job && job.status === 'running') { job.did = message.did || null; job.left = message.left || null; job.expected = message.expected || []; const stopped = job.ending && message.status === 'error'; finish(job, stopped ? 'stopped' : message.status, message.result, stopped ? 'stopped' : message.error) }
  }
}

// The body's process is gone (ended by us or by itself): what ran on it is over, a new one starts.
function bodyGone (why) {
  const was = child
  child = null
  const wasReady = ready
  ready = false
  if (was) { try { was.kill('SIGKILL') } catch (error) {} }
  if (wasReady) { restarts++; note('body_restarted', { why }) } else note('body_gone', { why })
  for (const job of [...running, ...paused]) {
    finish(job, 'stopped', null, `${why}: the body was started again, where it stood; listeners, timers and variables the code had left are gone, saved routines are kept`)
  }
  // A body that never got into the world (no server): try again, not in a tight loop.
  setTimeout(startBody, wasReady ? 0 : 3000)
}

function inWorld (ms = JOIN_MS) {
  if (ready) return Promise.resolve(true)
  return new Promise(resolve => {
    const done = (value) => { clearTimeout(timer); resolve(value) }
    const timer = setTimeout(() => { waiters = waiters.filter(w => w !== done); resolve(false) }, ms)
    waiters.push(done)
  })
}

// The watch: a body whose process says nothing, or that stands in the world without its
// physics ticking, is not a body any more. (A dead body's physics do not tick: it waits to be
// told to respawn, for as long as that takes.)
setInterval(() => {
  if (!child) return
  const now = Date.now()
  if (now - lastHeard > SILENT_MS) return bodyGone(`the code kept the body's process busy without a pause for ${SILENT_MS / 1000} s`)
  if (ready && lastState && lastState.connected && !lastState.dead && now - tickedAt > STILL_MS) return bodyGone(`the body's physics did not tick for ${STILL_MS / 1000} s`)
  if (!ready && now - child.born > JOIN_MS) return bodyGone(`the body was not in the world ${JOIN_MS / 1000} s after its process started`)
}, 500)

// ---------------------------------------------------------------- the job that has the body

function finish (job, status, result, error) {
  if (job.status !== 'running') return
  job.status = status; job.result = result; job.error = error
  if (job.did === undefined) job.did = (lastState && lastState.doing && lastState.doing[job.id]) || null   // (its process ended: what it had said last)
  job.ended = Date.now()
  if (!job.ended_by) job.ended_by = status === 'stopped' ? 'restart' : 'itself'
  if (job.timer) clearTimeout(job.timer)
  if (running.includes(job)) running.splice(running.indexOf(job), 1)
  if (paused.includes(job)) { paused.splice(paused.indexOf(job), 1); job.paused_ms += Date.now() - job.paused_at }
  for (const resolve of job.waiting.splice(0)) resolve()
}

function over (job, ms) {
  if (job.status !== 'running') return Promise.resolve(true)
  return new Promise(resolve => {
    const done = () => { clearTimeout(timer); resolve(true) }
    const timer = setTimeout(() => { job.waiting = job.waiting.filter(w => w !== done); resolve(false) }, ms)
    job.waiting.push(done)
  })
}

// Tell the job to stop; when its code has not returned GRACE_MS later, end the body's process.
// Resolves when the job is over and the body is free (in the world again after a restart).
function end (job, by) {
  if (job.status !== 'running') return Promise.resolve()
  if (!job.ending) {
    job.ended_by = by
    job.ending = (async () => {
      if (child) child.send({ op: 'stop', id: job.id })
      if (!await over(job, GRACE_MS)) {
        if (job.status === 'running') bodyGone(`the code did not return ${GRACE_MS / 1000} s after it was told to stop (${by})`)
        await inWorld()
      }
    })()
  }
  return job.ending
}

// A job has run as long as its call gave it: that is said once (the event over_time), and the
// job goes on. Whoever started it decides whether to stop it.
function overTime (job) {
  job.timer = null
  if (job.status !== 'running' || job.ending || job.over_time) return
  job.over_time = true
  note('over_time', { job: job.id, seconds: +(job.limit_ms / 1000).toFixed(1) })
}

async function startJob (code, args, limitMs, channels) {
  const mine = { channels: Array.isArray(channels) ? channels.filter(c => ALL.includes(c)) : null }   // ([]: it uses none)
  await Promise.all(running.filter(job => shares(job, mine)).map(job => end(job, 'another job')))
  if (!ready && !await inWorld(15000)) {
    return { id: null, status: 'error', started: Date.now(), ended: Date.now(), logs: [], result: null, error: 'the body is not in the world', from_seq: eventSeq, waiting: [] }
  }
  const id = 'j' + (++jobSeq)
  const job = { id, status: 'running', started: Date.now(), logs: [], result: null, error: null, from_seq: eventSeq, waiting: [], paused_ms: 0, channels: mine.channels }
  jobs.set(id, job)
  if (jobs.size > 200) jobs.delete(jobs.keys().next().value)
  running.push(job)
  if (limitMs) { job.limit_ms = limitMs; job.limit_at = Date.now() + limitMs; job.timer = setTimeout(() => overTime(job), limitMs) }
  child.send({ op: 'run', id, code, args: args || {}, channels: job.channels })
  return job
}

// The jobs that run on one of `channels` (none given: on any) keep what they have and wait (their time limits too);
// those channels are free. The ids of the jobs paused.
// It answers once the body has paused them: a step that must not be interrupted (h.atomic) is over first, within
// PAUSE_MS.
const PAUSE_MS = 6000
const pausing = new Map()   // job id -> what is called when the body says it paused it
async function pauseJobs (by, channels) {
  const taking = { channels: Array.isArray(channels) ? channels : null }
  const ids = []
  const made = []
  for (const job of running.filter(job => shares(job, taking) && !job.ending)) {
    running.splice(running.indexOf(job), 1)
    paused.push(job)
    job.paused_at = Date.now()
    if (job.timer) { clearTimeout(job.timer); job.timer = null; job.limit_left = job.limit_at - Date.now() }
    if (child) {
      made.push(new Promise(resolve => { pausing.set(job.id, resolve); setTimeout(resolve, PAUSE_MS) }))
      child.send({ op: 'pause', id: job.id, by: by || null })
    }
    note('job_paused', { job: job.id, by: by || null })
    ids.push(job.id)
  }
  await Promise.all(made)
  for (const id of ids) pausing.delete(id)
  return ids
}

// A paused job has its channels again and goes on. (A job that runs on one of them then is ended first.)
async function resumeJob (id) {
  const job = jobs.get(id)
  if (!job || !paused.includes(job) || job.status !== 'running') return null
  await Promise.all(running.filter(other => shares(other, job)).map(other => end(other, 'another job')))
  if (!paused.includes(job) || job.status !== 'running') return null
  paused.splice(paused.indexOf(job), 1)
  job.paused_ms += Date.now() - job.paused_at
  running.push(job)
  if (job.limit_left !== undefined && !job.over_time) { job.limit_at = Date.now() + Math.max(job.limit_left, 0); job.timer = setTimeout(() => overTime(job), Math.max(job.limit_left, 0)) }
  if (child) child.send({ op: 'resume', id: job.id })
  note('job_resumed', { job: job.id, paused_seconds: +(job.paused_ms / 1000).toFixed(2) })
  return job.id
}

function report (job) {
  return {
    id: job.id,
    status: job.status,                      // running | done | error | stopped
    channels: channelsOf(job),               // the channels it uses
    seconds: +(((job.ended || Date.now()) - job.started) / 1000).toFixed(2),
    paused: paused.includes(job),            // it waits to have the body again
    paused_seconds: +((job.paused_ms + (paused.includes(job) ? Date.now() - job.paused_at : 0)) / 1000).toFixed(2),
    ended_by: job.ended_by || null,          // itself | stop | another job | death | restart
    result: job.result,
    error: job.error,
    logs: job.logs.slice(-80),
    // What the code did to the world: {dug, placed (by block), broke (tools), moved (blocks), pulled_back (times the
    // server put the body back)}; so far, while it runs.
    did: job.status === 'running' ? ((lastState && lastState.doing && lastState.doing[job.id]) || null) : (job.did || null),
    // The timers and the listeners on the bot the code had left when it ended: they ended with it.
    cleared: job.left || null,
    // What the code expected with h.expect: {text, held, found} each.
    expected: job.expected || [],
    events: events.filter(e => e.seq > job.from_seq && e.kind !== 'health').slice(-60)
  }
}

// ---------------------------------------------------------------- saved routines

const NAME = /^[a-z][a-z0-9_]{0,60}$/
const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor
const file = (name) => path.join(STORE, 'skills', name + '.js')
const routineNames = () => fs.readdirSync(path.join(STORE, 'skills')).filter(f => f.endsWith('.js')).map(f => f.slice(0, -3)).sort()
const versions = (name) => fs.existsSync(path.join(STORE, 'history', name)) ? fs.readdirSync(path.join(STORE, 'history', name)).filter(f => f.endsWith('.js')).map(f => f.slice(0, -3)).sort() : []

// What a save or a removal replaces is kept: history/<name>/<when>.js.
function keep (name) {
  if (!fs.existsSync(file(name))) return
  fs.mkdirSync(path.join(STORE, 'history', name), { recursive: true })
  fs.copyFileSync(file(name), path.join(STORE, 'history', name, new Date().toISOString().replace(/[:.]/g, '-') + '.js'))
}

// ---------------------------------------------------------------- senses
//
// Values the caller defined that the body computes with every state it reports (body.js).
// Kept on disk like the routines, and loaded again by every body process.

const senseFile = (name) => path.join(STORE, 'senses', name + '.js')
const senseNames = () => fs.readdirSync(path.join(STORE, 'senses')).filter(f => f.endsWith('.js')).map(f => f.slice(0, -3)).sort()

function defineSense (name, code) {
  if (!child) return Promise.resolve({ defined: true, value: null, error: 'the body is in no world now: the sense is kept, and computed once it is in one' })
  return new Promise(resolve => {
    const ask = ++askSeq
    const timer = setTimeout(() => { asked.delete(ask); resolve({ defined: true, value: null, error: 'the body did not answer' }) }, 3000)
    asked.set(ask, (answer) => { clearTimeout(timer); resolve({ defined: answer.defined, value: answer.value, error: answer.error }) })
    child.send({ op: 'sense', name, code, ask })
  })
}

// ---------------------------------------------------------------- http

function body (request) {
  return new Promise((resolve, reject) => {
    let text = ''
    request.on('data', chunk => { text += chunk; if (text.length > 4e6) reject(new Error('too large')) })
    request.on('end', () => { try { resolve(text ? JSON.parse(text) : {}) } catch (error) { reject(new Error('body is not JSON')) } })
  })
}

const routes = {
  'GET /state': async () => {
    const live = ready && lastState && lastState.connected
    return {
      ...(lastState || {}),
      connected: !!live,
      deaths,
      restarts,
      skills: routineNames(),
      // The version of the game the body speaks, and how it logs in.
      version: VERSION,
      auth: process.env.MC_AUTH === 'microsoft' ? 'microsoft' : 'offline',
      // Where the libraries the body's code calls are, with their documentation and source.
      libraries: MODULES,
      jobs_running: running.map(job => job.id),
      jobs_paused: paused.map(job => job.id),
      events_seq: eventSeq,
      // The game window: there, on the body since its login, and where its own player is.
      window: VIEW_PORT ? { joined: !!viewer, attached, position: viewerSaid && { x: viewerSaid.x, y: viewerSaid.y, z: viewerSaid.z }, said_ms_ago: viewerSaid ? Date.now() - viewerSaid.t : null } : null
    }
  },
  // The events after `after` (of `kinds`, a comma list, when given). With wait_seconds it
  // answers as soon as there is one, or empty when that time is over: nobody has to ask again and again.
  'GET /events': async (q) => {
    const after = Number(q.after || 0)
    const kinds = q.kinds ? String(q.kinds).split(',') : null
    const found = () => events.filter(e => e.seq > after && (!kinds || kinds.includes(e.kind)))
    const wait = Math.min(Number(q.wait_seconds || 0), 60)
    if (wait > 0 && !found().length) {
      await new Promise(resolve => {
        const done = () => { clearTimeout(timer); awaited.delete(heard); resolve() }
        const heard = () => { if (found().length) done() }
        const timer = setTimeout(done, wait * 1000)
        awaited.add(heard)
      })
    }
    return { events: found().slice(-Number(q.limit || 200)), seq: eventSeq }
  },
  // Start code on the body, on the channels it says it uses (none: all). A running job that uses one of them is ended first.
  'POST /run': async (q, b) => {
    const job = await startJob(String(b.code || ''), b.args, b.limit_seconds ? b.limit_seconds * 1000 : null, b.channels)
    const wait = Math.min(Number(b.wait_seconds === undefined ? 30 : b.wait_seconds), 600) * 1000
    if (job.id && wait) await over(job, wait)
    return report(job)
  },
  'GET /job': async (q) => {
    const job = jobs.get(q.id)
    if (!job) return { status: 'error', error: 'no such job (the bridge itself was started again since)' }
    if (q.wait_seconds) await over(job, Math.min(Number(q.wait_seconds), 600) * 1000)
    return report(job)
  },
  // Ends the job `id`, running or paused; without one, every job. Answers when they are
  // over and the body is free.
  'POST /stop': async (q, b) => {
    const those = b.id ? [jobs.get(b.id)].filter(job => job && job.status === 'running') : [...running, ...paused]
    if (!those.length) return { stopped: 0 }
    await Promise.all(those.map(job => end(job, 'stop')))
    return { stopped: those.length, job: those[0].id, status: those[0].status }
  },
  // The jobs that run on one of `channels` (none: any) wait (answers their ids); /resume lets them go on.
  'POST /pause': async (q, b) => ({ paused: await pauseJobs(b.by, b.channels) }),
  'POST /resume': async (q, b) => {
    const ids = Array.isArray(b.ids) ? b.ids : b.id ? [b.id] : []
    const resumed = []
    for (const id of ids) { const done = await resumeJob(String(id)); if (done) resumed.push(done) }
    return { resumed }
  },
  'GET /skills': async () => ({ skills: routineNames() }),
  'GET /skill': async (q) => {
    if (!NAME.test(q.name || '')) return { error: 'no such skill' }
    const from = q.version ? path.join(STORE, 'history', q.name, q.version + '.js') : file(q.name)
    return fs.existsSync(from) ? { name: q.name, code: fs.readFileSync(from, 'utf8'), versions: versions(q.name) } : { error: q.version ? 'no such version' : 'no such skill', versions: versions(q.name) }
  },
  'POST /skill': async (q, b) => {
    if (!NAME.test(b.name || '')) return { error: 'name: lower case letters, digits, _' }
    const code = String(b.code)
    try { new AsyncFunction('bot', 'h', 'Vec3', 'skills', 'sleep', 'log', 'signal', 'args', 'senses', 'setTimeout', 'setInterval', 'setImmediate', 'clearTimeout', 'clearInterval', 'clearImmediate', code) } catch (error) { return { error: 'syntax: ' + error.message } }
    if (fs.existsSync(file(b.name)) && fs.readFileSync(file(b.name), 'utf8') !== code) keep(b.name)
    fs.writeFileSync(file(b.name), code)
    if (child) child.send({ op: 'load', name: b.name, code })
    return { saved: b.name, versions: versions(b.name) }
  },
  'POST /skill/remove': async (q, b) => {
    if (!NAME.test(b.name || '')) return { error: 'no such skill' }
    keep(b.name)
    fs.rmSync(file(b.name), { force: true })
    if (child) child.send({ op: 'unload', name: b.name })
    note('routine_removed', { name: b.name, why: String(b.why || '').slice(0, 500) })
    return { removed: b.name }
  },
  'GET /senses': async () => {
    const now = (lastState && lastState.sensed) || {}; const errors = (lastState && lastState.sense_errors) || {}
    return Object.fromEntries(senseNames().map(name => [name, { code: fs.readFileSync(senseFile(name), 'utf8'), value: name in now ? now[name] : null, error: errors[name] || null }]))
  },
  'POST /sense': async (q, b) => {
    if (!NAME.test(b.name || '')) return { defined: false, error: 'name: lower case letters, digits, _' }
    const code = String(b.code)
    try { new Function('bot', 'Vec3', 'h', code) } catch (error) { return { defined: false, error: 'syntax: ' + error.message } }
    fs.writeFileSync(senseFile(b.name), code)
    return { name: b.name, ...(await defineSense(b.name, code)) }
  },
  'POST /sense/remove': async (q, b) => {
    if (!NAME.test(b.name || '')) return { removed: false }
    const was = fs.existsSync(senseFile(b.name))
    fs.rmSync(senseFile(b.name), { force: true })
    // The body says when it no longer computes it: every state it reports after that is without
    // it, and the one held here is put right at once.
    if (child) {
      await new Promise(resolve => {
        const ask = ++askSeq
        const timer = setTimeout(() => { asked.delete(ask); resolve() }, 1000)
        asked.set(ask, () => { clearTimeout(timer); resolve() })
        child.send({ op: 'unsense', name: b.name, ask })
      })
    }
    if (lastState && lastState.sensed) delete lastState.sensed[b.name]
    if (lastState && lastState.sense_errors) delete lastState.sense_errors[b.name]
    return { removed: was }
  },
  // Hazards and route rules of the body's walking (nav.js): {what: define | undefine | avoid | unavoid | list, kind:
  // hazard | rule, name, code, args}. A definition is kept on disk like a sense and loaded by every body process;
  // what is put in force here stays until it is taken out. Answers {ok, error, listed}.
  'POST /nav': async (q, b) => {
    const what = String(b.what || 'list')
    if (what === 'define' || what === 'undefine') {
      if (!NAME.test(b.name || '') || !['hazard', 'rule'].includes(b.kind)) return { ok: false, error: 'kind: hazard or rule; name: lower case letters, digits, _' }
      const file = path.join(STORE, 'nav', b.kind + '-' + b.name + '.js')
      if (what === 'define') {
        try { b.kind === 'hazard' ? new Function('bot', 'Vec3', 'args', 'moving', String(b.code)) : new Function('step', 'bot', 'Vec3', 'args', String(b.code)) } catch (error) { return { ok: false, error: 'syntax: ' + error.message } }
        fs.writeFileSync(file, String(b.code))
      } else fs.rmSync(file, { force: true })
    }
    if (!child) {
      // No body is in a world: what is defined is kept (the body loads it when it comes into one) and listed
      // from where it is kept; nothing can be in force.
      if (what === 'avoid' || what === 'unavoid') return { ok: false, error: 'the body is in no world now: nothing can be put in force or taken out' }
      const kept = (kind) => fs.existsSync(path.join(STORE, 'nav')) ? fs.readdirSync(path.join(STORE, 'nav')).map(f => (f.match(new RegExp('^' + kind + '-([a-z0-9_]+)\\.js$')) || [])[1]).filter(Boolean).sort() : []
      return { ok: true, listed: { hazards: kept('hazard'), rules: kept('rule'), active: [], errors: {} } }
    }
    return new Promise(resolve => {
      const ask = ++askSeq
      const timer = setTimeout(() => { asked.delete(ask); resolve({ ok: false, error: 'the body did not answer' }) }, 3000)
      asked.set(ask, (answer) => { clearTimeout(timer); resolve({ ok: answer.ok, error: answer.error, removed: answer.removed, listed: answer.listed }) })
      child.send({ op: 'nav', what, kind: b.kind, name: b.name, code: b.code === undefined ? undefined : String(b.code), args: b.args, ask })
    })
  },
  // Whether a game server answers now (a world is being played).
  'GET /server': async () => new Promise(resolve => serverAnswers(up => resolve({ answers: up }))),
  'POST /chat': async (q, b) => { if (ready) child.send({ op: 'chat', text: String(b.text) }); return { sent: ready } },
  // A dead body respawns when it is told to, not by itself: {respawned, dead} once it stands again (10 s at most).
  'POST /respawn': async () => {
    if (!ready || !lastState) return { respawned: false, dead: null, why: 'the body is not in the world' }
    if (!lastState.dead) return { respawned: false, dead: false, why: 'the body is alive' }
    child.send({ op: 'respawn' })
    for (let k = 0; k < 100 && lastState && lastState.dead; k++) await new Promise(resolve => setTimeout(resolve, 100))
    return { respawned: !(lastState && lastState.dead), dead: !!(lastState && lastState.dead) }
  }
}

startBody()

http.createServer(async (request, response) => {
  const url = new URL(request.url, 'http://localhost')
  const route = routes[request.method + ' ' + url.pathname]
  let out; let code = 200
  try {
    if (!route) { code = 404; out = { error: 'unknown route', routes: Object.keys(routes) } } else {
      out = await route(Object.fromEntries(url.searchParams), request.method === 'POST' ? await body(request) : {})
    }
  } catch (error) { code = 500; out = { error: String(error && error.message) } }
  response.writeHead(code, { 'content-type': 'application/json' })
  response.end(JSON.stringify(out))
}).listen(BRIDGE_PORT, '127.0.0.1', () => console.log(`bridge on 127.0.0.1:${BRIDGE_PORT}, up ${new Date(started).toISOString()}`))

process.on('uncaughtException', (error) => { note('bridge_error', { message: String(error && error.message) }); console.error(error) })
process.on('unhandledRejection', (error) => { note('bridge_error', { message: String(error && error.message) }) })
process.on('exit', () => { if (child) { try { child.kill('SIGKILL') } catch (error) {} } })
