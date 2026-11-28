guide("window-types"): the window types of Minecraft 1.16.1 and their slot layout.

For each type: window.type, the number of slots, the inventory section (first slot to
last slot; window.inventoryStart is the first, window.inventoryEnd the last + 1), and
window.craftingResultSlot (-1: none). The container section is slots 0 to
inventoryStart - 1. The hotbar is the last 9 slots of the inventory section.

  type                      slots  inventory  result
  minecraft:inventory         46    9 to 44      0     bot.inventory; slot 45 off hand
  minecraft:generic_9x1       45    9 to 44     -1
  minecraft:generic_9x2       54   18 to 53     -1
  minecraft:generic_9x3       63   27 to 62     -1
  minecraft:generic_9x4       72   36 to 71     -1
  minecraft:generic_9x5       81   45 to 80     -1
  minecraft:generic_9x6       90   54 to 89     -1
  minecraft:generic_3x3       45    9 to 44     -1
  minecraft:anvil             39    3 to 38      2
  minecraft:beacon            37    1 to 36     -1
  minecraft:blast_furnace     39    3 to 38      2
  minecraft:brewing_stand     41    5 to 40     -1
  minecraft:crafting          46   10 to 45      0
  minecraft:enchantment       38    2 to 37     -1
  minecraft:furnace           39    3 to 38      2
  minecraft:grindstone        39    3 to 38      2
  minecraft:hopper            41    5 to 40     -1
  minecraft:lectern           37    1 to 36     -1
  minecraft:loom              40    4 to 39      3
  minecraft:merchant          39    3 to 38      2
  minecraft:shulker_box       63   27 to 62     -1
  minecraft:smithing          39    3 to 38      2
  minecraft:smoker            39    3 to 38      2
  minecraft:cartography       39    3 to 38      2
  minecraft:stonecutter       38    2 to 37      1

  The server names the type by a number in the open-window packet: 0 for
  minecraft:generic_9x1, then up by one in the order of the table, to 23 for
  minecraft:stonecutter. window.type holds the name.
  A horse's window has type 'HorseWindow': its container section has as many slots as
  the server announces (n), its inventory section is n to n + 35, result slot -1.

Every type has window.requiresConfirmation true: bot.clickWindow waits for the server's
transaction packet for each click.

The prismarine-windows module (require('prismarine-windows')(bot.version)).
windows.createWindow(id, type, title, slotCount) -> Window | null
  type: a name from the table or its number. For an unknown type with slotCount given it
  builds a window with slotCount container slots followed by 36 inventory slots and
  result slot -1; with slotCount undefined it returns null. It creates a local object
  only; nothing is opened on the server.
windows.Window                       the Window class
  new Window(id, type, title, slotCount, inventorySlotsRange = { start: 27, end: 62 },
  craftingResultSlot = -1, requiresConfirmation = true); end is the last slot, included.
windows.windows                      the table above as an object keyed by type name:
  { type: number, inventory: { start, end }, slots, craft, requireConfirmation, key }
