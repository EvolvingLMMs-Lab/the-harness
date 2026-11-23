guide("sound"): the events emitted when the server plays a sound.

The server sends a sound in one of two packets: sound_effect, which names the sound by a
number, or named_sound_effect, which names it by a string.

'hardcodedSoundEffectHeard' (soundId, soundCategory, position, volume, pitch)
  Emitted for every sound_effect packet.
  soundId: the number of the sound in the packet. bot.registry has no table of sounds
  for 1.16.1 (bot.registry.sounds is undefined), so the number is not turned into a name.
  soundCategory: the number of the category in the packet.
  position: a Vec3. The packet holds the position multiplied by 8 as integers; the event
  gives each coordinate divided by 8, so the position is exact to 1/8 of a block.
  volume, pitch: the numbers in the packet (floats).

'soundEffectHeard' (soundName, position, volume, pitch)
  Emitted for every named_sound_effect packet.
  soundName: 'minecraft:' followed by the name in the packet with every '.' replaced by
  '_'. A packet name 'entity.pig.ambient' gives 'minecraft:entity_pig_ambient'; a packet
  name 'minecraft:entity.pig.ambient' gives 'minecraft:minecraft:entity_pig_ambient'.
  position, volume, pitch: as above.
  Right after it, for the same packet, the bot also emits
  'hardcodedSoundEffectHeard' (0, 'master', position, volume, pitch).

The entity_sound_effect packet (a sound attached to an entity) emits nothing.
