guide("location"): the Location class: a position split into chunk coordinates.

const { Location } = require('mineflayer')
new Location(point)
  point: a Vec3 with any real coordinates. The object holds:
  loc.floored          Vec3: point with each coordinate rounded down
  loc.blockPoint       Vec3: floored modulo 16 on each axis, the place inside a
                       16 x 16 x 16 section; 0 to 15 on each axis, also for negative
                       coordinates
  loc.chunkCorner      Vec3: floored minus blockPoint, the low corner of that section
                       (each coordinate a multiple of 16)
  loc.blockIndex       number: blockPoint.x + 16 * blockPoint.z + 256 * blockPoint.y
  loc.biomeBlockIndex  number: blockPoint.x + 16 * blockPoint.z
  loc.chunkYIndex      number: floor(point.y / 16)

  new Location(new Vec3(-1.5, 70.2, 33)):
    floored (-2, 70, 33), blockPoint (14, 6, 1), chunkCorner (-16, 64, 32),
    blockIndex 14 + 16 + 1536 = 1566, biomeBlockIndex 30, chunkYIndex 4

The class is exported by the mineflayer module. bot has no property that holds a
Location, and no bot call takes or returns one.
