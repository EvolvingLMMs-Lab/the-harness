guide("registry-lookups"): bot.registry: every table of game data it holds for 1.16.1.

bot.registry is set while the bot is created, before any event of the game. Its tables
are plain objects and arrays loaded from data files. Nothing in the bot changes them on
1.16.1. Every part of the bot reads the same objects, so writing to a record changes
what the bot's own calls read afterwards.

A table named X is keyed by numeric id, XByName by the name string, XArray is the list
of all records. The same record object is reached through all three.
  bot.registry.itemsByName.stick.id      -> 599
  bot.registry.items[599].name           -> 'stick'
  bot.registry.blocksByName.stone.id     -> 1
A key that is not in a table gives undefined.

Tables (records on 1.16.1), and the page that lists the fields of a record.
  blocks, blocksByName, blocksArray (763)        guide("registry-blocks")
  blocksByStateId (17104 state ids)              guide("registry-block-states")
  blockCollisionShapes                           guide("registry-block-states")
  items, itemsByName, itemsArray (974)           guide("registry-items-and-foods")
  foods, foodsByName, foodsArray (40)            guide("registry-items-and-foods")
  entities, entitiesByName, entitiesArray (107)  guide("registry-entities")
  mobs (101), objects (0)                        guide("registry-entities")
  recipes (562 result ids)                       guide("registry-recipes")
  effects, effectsByName, effectsArray (32)      guide("registry-effects-enchantments")
  enchantments, enchantmentsByName, enchantmentsArray (34)
                                                 guide("registry-effects-enchantments")
  materials (8)                                  guide("registry-materials")
  blockLoot, blockLootArray (701)                guide("registry-loot")
  entityLoot, entityLootArray (71)               guide("registry-loot")
  biomes, biomesByName, biomesArray (79)         guide("registry-biomes-and-windows")
  windows, windowsByName, windowsArray (14)      guide("registry-biomes-and-windows")
  instruments, instrumentsArray (16)             guide("registry-other-tables")
  attributes, attributesByName, attributesArray (13)   guide("registry-other-tables")
  particles, particlesByName, particlesArray (72)      guide("registry-other-tables")
  mapIcons, mapIconsByName, mapIconsArray (27)   guide("registry-other-tables")
  language (4754 keys)                           guide("registry-other-tables")
  tints, commands, loginPacket, protocol, protocolYaml   guide("registry-other-tables")

Keys that differ from the pattern.
  blockLoot is keyed by block name, entityLoot by entity name; they have no ByName form.
  attributes is keyed by the resource string ('generic.max_health'), attributesByName
  by the short name ('maxHealth').
  windows is keyed by the window type string ('minecraft:furnace'), windowsByName by the
  display name ('Furnace').
  effectsByName uses capitalised names without spaces ('Speed', 'MiningFatigue').
  recipes is keyed by the numeric id of the item made; it has no ByName form.
  instruments has no ByName form.

Absent on 1.16.1 (undefined): sounds, soundsByName, soundsArray, blockMappings,
blockStates, protocolComments, defaultSkin, dimensionsById, dimensionsByName,
dimensionsArray, chatFormattingById, chatFormattingByName.
Empty on 1.16.1: objects ({}).

Version and feature checks (version, type, isNewerOrEqualTo, isOlderThan,
supportFeature, loadDimensionCodec, writeDimensionCodec): guide("registry-version").
