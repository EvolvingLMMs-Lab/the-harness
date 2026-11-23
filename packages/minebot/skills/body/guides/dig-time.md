guide("dig-time"): bot.digTime and block.digTime: how the time of a dig is counted.

bot.digTime(block) -> milliseconds
  Calls block.digTime with the bot's state at this moment:
    heldItemType   bot.heldItem.type, or null with an empty hand
    creative       bot.game.gameMode === 'creative'
    inWater        the block at the eyes (bot.entity.position plus eyeHeight) is named
                   'water'. A waterlogged block or a water plant there does not count
    notOnGround    !bot.entity.onGround
    enchantments   those of the held item plus those of the helmet (inventory slot 5)
    effects        bot.entity.effects
  bot.dig calls it once, before it turns the head, and waits that long.

block.digTime(heldItemType, creative, inWater, notOnGround, enchantments = [],
              effects = {}) -> milliseconds
  enchantments: array of { name, lvl }. effects: { effectId: { amplifier } }; the level of
  an effect is amplifier + 1.
  1. creative: returns 0.
  2. speed = 1. When bot.registry.materials[block.material] has the held item, speed is
     the number there. block.material is the kind of tool the 1.16.1 game gives a speed on
     the block (guide("registry-materials")):
       pickaxe                 pickaxe: wooden 2, stone 4, iron 6, diamond 8, netherite 9,
                               golden 12
       axe                     axe: the same numbers
       shovel                  shovel: the same numbers
       hoe                     hoe: the same numbers
       axe+sword1.5            axe: the same numbers; any sword 1.5
       hoe+sword1.5+shears15   hoe: the same numbers; any sword 1.5; shears 15
       sword15+shears15        any sword 15; shears 15
       shears5                 shears 5
       hand                    no item has a speed
  3. Efficiency level L on the list, and speed > 1: speed += L * L + 1.
  4. Haste or Conduit Power, the higher level H: speed *= 1 + 0.2 * H.
  5. Mining Fatigue: speed *= 0.3 (level 1), 0.09 (2), 0.0027 (3), 0.00081 (4 and more).
  6. inWater, and no aqua_affinity on the list: speed /= 5.
  7. notOnGround: speed /= 5.
  8. progress per tick = speed / block.hardness / (30 when block.canHarvest(heldItemType),
     else 100).
  9. hardness -1: returns Infinity. Progress 1 or more: returns 0. Otherwise returns
     ceil(1 / progress) * 50.

  Examples with nothing else in play: stone (hardness 1.5) by hand 7500, with a wooden
  pickaxe 1150, a stone pickaxe 600, an iron pickaxe 400, a netherite pickaxe 250, a golden
  pickaxe with Efficiency 5 100. A log by hand 3000, with a stone axe 750. Dirt by hand
  750, with a stone shovel 200. Leaves by hand 300, with a stone hoe 100, with shears 0.
  Iron ore with a wooden pickaxe 7500 (it does not harvest it), with a stone pickaxe 1150.
  Obsidian with a diamond pickaxe 9400, with an iron pickaxe 41700.

Choosing the item to dig with.
  The fastest item is the one with the shortest block.digTime: compute it for each item in
  the inventory and for null (the bare hand). A block with harvestTools drops nothing
  unless one of those items digs it: stone dug by hand, or with an item that is no
  pickaxe, takes 7500 and leaves no cobblestone. bot.dig digs with what is in the hand and
  equips nothing.

Facts of the registry that enter the count. The body takes hardness, material and
harvestTools from the 1.16.1 game itself, in place of Mineflayer's tables.
  - 12 blocks have hardness -1 and diggable false, and give Infinity: bedrock,
    moving_piston, nether_portal, end_portal, end_portal_frame, end_gateway, barrier,
    command_block, repeating_command_block, chain_command_block, structure_block, jigsaw.
  - Water and lava have hardness 100: 150000 by hand.
  - Hardness 0 gives 0 for every block (air, torches, saplings, grass, ...): 145 blocks.
  - harvestTools lists the items as the game has them: stone lists all six pickaxes, the
    netherite one among them.
