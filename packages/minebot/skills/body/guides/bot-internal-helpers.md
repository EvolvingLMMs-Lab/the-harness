guide("bot-internal-helpers"): the helper modules inside mineflayer: promise_utils,
conversions, math. They are not on the bot; code reaches them with require.

require('mineflayer/lib/promise_utils')
  sleep(ms) -> Promise
    Resolves with undefined after ms milliseconds (setTimeout).
  once(emitter, event, timeout = 20000) -> Promise
    onceWithCleanup(emitter, event, { timeout }).
  onceWithCleanup(emitter, event, { timeout = 0, checkCondition, signal } = {}) -> Promise
    Listens to event on emitter. At each event: with a checkCondition function, calls
    checkCondition(...args); a falsy result skips the event; an error thrown by it
    rejects the promise with that error. Else resolves with the array of the event's
    arguments.
    timeout: a number above 0 rejects after that many ms with
    'Event <event> did not fire within timeout of <timeout>ms'. 0 or less: no time limit.
    signal: an AbortSignal. When it aborts (or is already aborted) the promise rejects
    with signal.reason when that is an Error, else with
    'Waiting for event <event> was aborted'.
    The listener is removed when the promise settles, whichever way.
  withTimeout(promise, timeout) -> Promise
    Settles as promise does, or rejects with 'Promise timed out.' after timeout ms,
    whichever comes first. The given promise goes on running after the rejection.
  createTask() -> { done, promise, finish(result), cancel(err) }
    done is false. finish(result) resolves promise with result; cancel(err) rejects it
    with err. The first of the two calls sets done to true; later calls do nothing.
  createDoneTask() -> { done: true, promise, finish, cancel }
    promise is already resolved; finish and cancel do nothing.

require('mineflayer/lib/conversions')
  The bot's angles are radians (guide("look")); the server's are degrees.
  toRadians(degrees), toDegrees(radians)
  toNotchianYaw(yaw) = toDegrees(PI - yaw)        bot yaw to server yaw
  toNotchianPitch(pitch) = toDegrees(-pitch)      bot pitch to server pitch
  fromNotchianYaw(degrees)      server yaw to bot yaw, in 0 to 2*PI
  fromNotchianPitch(degrees)    server pitch to bot pitch, in -PI to PI
  fromNotchianYawByte(b), fromNotchianPitchByte(b)   the same from a byte, 256 to a turn
  fromNotchVelocity(vel) -> Vec3    each of vel.x, vel.y, vel.z divided by 8000: the
                                    server's velocity units to blocks a tick

require('mineflayer/lib/math')
  clamp(min, x, max) -> number      x limited to min..max; the order of arguments is
                                    (min, x, max)
  euclideanMod(numerator, denominator) -> number    the remainder, made positive by
                                    adding the denominator when it is negative
