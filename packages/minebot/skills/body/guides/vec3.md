guide("vec3"): the Vec3 class: every method, and whether it makes a new vector.

new Vec3(x, y, z)        fields x, y, z (numbers; no check)
Positions (block.position, entity.position, bot.entity.position) are Vec3. A method that
"changes v" writes into the vector it is called on and returns that same vector: called
on bot.entity.position or block.position it changes that object.

Return a new Vec3; v is unchanged.
v.offset(dx, dy, dz)     v + (dx, dy, dz)
v.plus(other)            v + other
v.minus(other)           v - other
v.scaled(k)              v * k
v.floored()              each part rounded down
v.rounded()              each part rounded to the nearest whole number
v.abs()                  each part made positive
v.clone()                a copy
v.unit()                 v / its length; a copy when the length is 0
v.min(other), v.max(other)   the smaller / larger of the two on each axis
v.modulus(other)         each part modulo the other's part, result 0 or positive
v.cross(other)           cross product
v.xzy()                  (x, z, y)

Change v and return v.
v.set(x, y, z)           writes the three parts
v.update(other)          copies other's parts into v
v.add(other)             v += other
v.subtract(other)        v -= other
v.translate(dx, dy, dz)  v += (dx, dy, dz)
v.scale(k)               v *= k
v.multiply(other)        each part times the other's part
v.divide(other)          each part divided by the other's part
v.floor()                each part rounded down
v.round()                each part rounded to the nearest whole number
v.normalize()            v /= its length; unchanged when the length is 0

Return a number.
v.distanceTo(other)      straight-line distance
v.distanceSquared(other) its square
v.xzDistanceTo(other)    distance ignoring y
v.xyDistanceTo(other)    distance ignoring z
v.yzDistanceTo(other)    distance ignoring x
v.manhattanDistanceTo(other)   |dx| + |dy| + |dz|
v.norm()                 the length of v
v.dot(other), v.innerProduct(other)   dot product
v.volume()               x * y * z
v.at(i)                  part number i: 0 x, 1 y, 2 z

Return something else.
v.equals(other, error = 0) -> boolean   every part differs by at most error
v.isZero() -> boolean                   all three parts are 0
v.toString() -> '(x, y, z)'             one space after each comma: '(1, 64, -3)'
v.toArray() -> [x, y, z]
v.xz() -> [x, z], v.xy() -> [x, y], v.yz() -> [y, z]

The module function, require('vec3'), builds a Vec3 and runs parseFloat on each part:
  vec3(x, y, z); vec3([x, y, z]); vec3({ x, y, z }); vec3('(1, 2, 3)'); vec3() gives
  (0, 0, 0). A string of another form throws 'vec3: cannot parse: <string>'.
  require('vec3').Vec3 is the class.
