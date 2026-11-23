guide("dig-face"): the forceLook and digFace parameters of bot.dig.

bot.dig(block, forceLook, digFace)
  Digs a block. The whole call, with its steps and the ways it ends: guide("dig-block").

The face number is sent to the server with the start and the end of the dig, and is in
bot.targetDigFace. Faces: 0 bottom (-y), 1 top (+y), 2 north (-z), 3 south (+z),
4 west (-x), 5 east (+x). It starts at 1 (top).

forceLook.
  'ignore'            the head does not turn. digFace is not read; the face is 1.
  true (any truthy value other than 'ignore')
                      bot.entity.yaw and pitch are set at once and bot.dig goes on
                      without waiting.
  false, undefined (default)
                      bot.entity.yaw and pitch are set at once; the yaw sent to the
                      server moves towards it on every 50 ms tick, at
                      bot.physics.yawSpeed radians per second. bot.dig waits until the
                      sent yaw is within 0.001 radians of the new yaw.
  The value is passed to bot.lookAt(point, forceLook). When the head already points
  there, there is no wait in either case.

digFace.
  undefined, null, a function, or any value not listed below ('auto')
                      looks at the centre of the block (position + 0.5). Face 1.
  a Vec3 with a non-zero x, y or z
                      the face: x > 0 east, x < 0 west; else y > 0 top, y < 0 bottom; else
                      z > 0 south, z < 0 north (x is read first, then y, then z).
                      Looks at centre + digFace * 0.5: for (0, 1, 0) the middle of the
                      top face.
  'raycast'           chooses a face the eyes have a free line to:
    1. The eyes are bot.entity.position plus eyeHeight. On each axis, the face turned
       towards the eyes is a candidate when the eyes are more than 0.5 from the block's
       centre on that axis. Order: y, x, z. At most three candidates.
    2. For each candidate it casts a ray of length 5 from the eyes to the middle of that
       face. The first block with shapes on the ray decides. Its hit point is nearer to
       the eyes than the face's middle: the candidate is dropped and the block counts as
       a nearer block. Otherwise, when it is at the position of the block to dig: the
       candidate is kept, with the face number and the hit point of the ray.
    3. One or more kept: it looks at the hit point nearest to the eyes and sends that
       face.
    4. None kept, no ray met a nearer block, and block.shapes is empty (a plant, a
       torch): it looks at the centre; face 1.
    5. Otherwise it rejects with 'Block not in view'. That happens before anything is
       sent and before a running dig is stopped.
