guide("particle"): the 'particle' event and the Particle object.

'particle' (particle)
  Emitted for every world_particles packet. particle is a Particle.

Particle fields.
particle.id                  the number of the particle kind, 0 to 71 on 1.16.1
particle.name                the name of that kind in bot.registry.particles, for example
                             'flame', 'crit', 'portal', 'explosion'; undefined for a
                             number the table does not hold
particle.position            Vec3, where the particles appear
particle.offset              Vec3, the spread of the particles on each axis as sent
particle.count               how many particles the packet asks for
particle.movementSpeed       the float 'particleData' of the packet (the particles' speed)
particle.longDistanceRender  true or false, as sent

The extra data some kinds carry (the block of a 'block' particle, the colour of 'dust',
the item of 'item') is not copied into the object.

bot.registry.particles[id] -> { id, name }
bot.registry.particlesByName[name] -> { id, name }
bot.registry.particlesArray              the 72 records

new Particle(id, position, offset, count = 1, movementSpeed = 0, longDistanceRender = false)
  Particle = require('mineflayer').Particle(bot.registry), or particle.constructor.
  id: a number or a name. The id and name of the matching record are copied onto the
  object; with no matching record, particle.id is the argument and name is undefined.
Particle.fromNetwork(packet) -> Particle     builds one from a world_particles packet
