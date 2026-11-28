guide("chest"): opening chests and other containers: bot.openContainer, openChest.

bot.openContainer(containerToOpen, direction, cursorPos) -> Promise<Window>
  direction: Vec3, default (0, 1, 0). cursorPos: Vec3, default (0.5, 0.5, 0.5).
bot.openChest        the same function under another name
bot.openDispenser    the same function under another name

What it accepts.
  A Block whose name is one of: chest, trapped_chest, ender_chest, barrel, dispenser,
  dropper, hopper, shulker_box, the 16 coloured shulker boxes (white_shulker_box,
  orange_, magenta_, light_blue_, yellow_, lime_, pink_, gray_, light_gray_, cyan_,
  purple_, blue_, brown_, green_, red_, black_shulker_box), generic, container.
  An Entity object of any kind (the code does not check which).
  Anything else, a Block with another name (a furnace, a crafting table) included:
  rejects with 'containerToOpen is neither a block nor an entity'. Nothing is sent.

Steps for a Block.
  bot.openBlock(block, direction, cursorPos): the bot turns its head to the centre of the
  block and sends one use-block packet, then waits for the bot event 'windowOpen',
  20 seconds at most.
  direction: which face of the block the packet names. y > 0: top (the default); y < 0:
    bottom; else z < 0: north; z > 0: south; else x < 0: west; x > 0: east.
  cursorPos: the point on the block the packet names, each coordinate from 0 to 1.
  The code checks no distance to the block.

Steps for an Entity.
  bot.openEntity(entity): the bot turns its head to the entity's position plus 1 block
  up, sends one interact packet for the entity with the main hand, then waits for the bot
  event 'windowOpen', 20 seconds at most. direction and cursorPos are not used.

After the window opens.
  The window's type has to start with one of 'minecraft:generic', 'minecraft:chest',
  'minecraft:dispenser', 'minecraft:ender_chest', 'minecraft:shulker_box',
  'minecraft:hopper', 'minecraft:container', 'minecraft:dropper',
  'minecraft:trapped_chest', 'minecraft:barrel' or a coloured shulker box name. The
  window types of 1.16.1 that pass, with the number of container slots:
    minecraft:generic_9x1  9     minecraft:generic_9x4  36    minecraft:generic_3x3  9
    minecraft:generic_9x2  18    minecraft:generic_9x5  45    minecraft:hopper       5
    minecraft:generic_9x3  27    minecraft:generic_9x6  54    minecraft:shulker_box  27
  Another type: rejects with 'Non-container window used as a container: ' followed by the
  window as JSON; that window stays open (bot.currentWindow).
  Resolves with the Window. Its members: guide("chest-items").

Other rejections.
  'Event windowOpen did not fire within timeout of 20000ms': no window opened within
  20 seconds of the packet.

Slots of the returned window.
  0 to N-1: the container, N its number of slots (window.inventoryStart is N).
  N to N+35: the bot's inventory (27 slots, then the 9 hotbar slots);
  window.inventoryEnd is N+36. Slot s of bot.inventory (9 to 44) is slot s - 9 + N of the
  window.
