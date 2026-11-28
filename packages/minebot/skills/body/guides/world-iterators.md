guide("world-iterators"): the iterator classes of prismarine-world.

They are at require('prismarine-world').iterators. bot.world.raycast passes its
RaycastIterator to the matcher function as the second argument. Each next() returns the
following position, or null at the end.

BlockFace
  { UNKNOWN: -999, BOTTOM: 0, TOP: 1, NORTH: 2, SOUTH: 3, WEST: 4, EAST: 5 }
  BOTTOM is the -y face, TOP +y, NORTH -z, SOUTH +z, WEST -x, EAST +x.

new RaycastIterator(pos, dir, maxDistance)
  Walks the block positions crossed by the ray from pos (Vec3) along dir (Vec3 of
  length 1).
  iterator.next() -> { x, y, z, face } | null
    The next block position on the ray, with the face it is entered by. The position
    holding pos is not returned (it is in iterator.block before the first call, with face
    -999). Returns null once the next position starts at more than maxDistance from pos.
    The same object is returned and changed on every call.
  iterator.intersect(shapes, offset) -> { pos, face } | null
    shapes: array of boxes [x0, y0, z0, x1, y1, z1]; offset: Vec3 added to them (a
    block's position). Returns the nearest point where the line of the ray enters one of
    the boxes, and the face entered; null when it crosses none. The line is not cut at
    maxDistance, and it extends behind pos.

new OctahedronIterator(start, maxDistance)
  start: Vec3, floored. next() returns, layer by layer, the positions at |dx| + |dy| +
  |dz| = 1, then 2, ... up to maxDistance from start; start itself is not returned. A
  position can be returned more than once. iterator.apothem is the number of the layer
  being returned. bot.findBlocks walks sections with it.

new ManhattanIterator(x, y, maxDistance)       (also exported as ManathanIterator)
  next() returns Vec3(x', 0, z'): first (x, 0, y), then rings around it at growing
  |dx| + |dz|, ending before the ring number floor(maxDistance).

new SpiralIterator2d(pos, maxDistance)
  next() returns pos, then positions on a square spiral around it in the x-z plane
  (y unchanged), each one step from the one before:
  floor(((floor(maxDistance) - 0.5) * 2) ^ 2) positions in all (9 for maxDistance 2,
  25 for 3).
