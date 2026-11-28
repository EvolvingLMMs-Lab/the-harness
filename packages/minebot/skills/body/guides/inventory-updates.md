guide("inventory-updates"): what changes bot.inventory, and its state while another window
is open.

What writes the slots of bot.inventory.
  A set-slot packet with window id 0: that slot is replaced by a new Item (or null).
  A window-items packet with window id 0: every slot is replaced.
  A click made with bot.clickWindow while no other window is open, once the server
  confirms it: the click is applied to the slots as in guide("window-click-modes").
  bot.closeWindow(window): the inventory section of the closed window is copied in.
  bot.creative.setInventorySlot does not write a slot itself on 1.16.1; the server's
  set-slot packet does.
  Each replacement puts a new Item object in the slot. An Item object read earlier is not
  updated in place by a packet; a confirmed click changes the count of existing objects
  and moves the same objects between slots (their slot field is rewritten).

While another window is open (bot.currentWindow is not null).
  The server sends slot changes with the id of the open window. They are written to
  bot.currentWindow.slots, which has its own copy of the 36 inventory slots at
  bot.currentWindow.inventoryStart to inventoryEnd - 1. bot.inventory is changed only by
  packets with window id 0.
  Confirmed clicks are applied to bot.currentWindow, not to bot.inventory.
  bot.heldItem and bot.entity.equipment read bot.inventory, so they show the state from
  before the window opened plus any window-id-0 packets.
  A packet whose window id is neither 0 nor the id of the open window is ignored, except
  the two cases below.

When a window closes.
  bot.closeWindow(window) (and window.close()) copies slot i of the window, for i from
  window.inventoryStart to window.inventoryEnd - 1, to bot.inventory slot
  i - window.inventoryStart + 9, for each slot whose type, count, metadata or nbt differ.
  Each copied slot emits 'updateSlot' on bot.inventory.
  After that, a set-slot packet carrying the closed window's id and a slot in its
  inventory section is still applied to the matching bot.inventory slot. A window-items
  packet carrying the closed window's id and exactly as many items as that window has
  slots is applied to the whole inventory section the same way. This lasts until the
  next window opens, or a 'login' or 'respawn' packet arrives.
  When the server closes the window (a close-window packet), nothing is copied:
  bot.currentWindow becomes null and 'windowClose' is emitted.

Events.
bot.inventory 'updateSlot' (slot, oldItem, newItem)     every write of a slot, also when
                                                        the new value equals the old one
bot.inventory 'updateSlot:N' (oldItem, newItem)         the same, for slot number N
bot 'setSlot:ID' (oldItem, newItem)
  Emitted after a set-slot packet is applied to the window with id ID (0 for
  bot.inventory), and for each inventory slot written by a trailing packet of a closed
  window (with ID 0).
bot 'setWindowItems:ID' ()
  Emitted after a window-items packet for window ID (0, or the open window) is applied.
bot 'heldItemChanged' (heldItem)     see guide("hand-held-item")

bot._setSlot(slotId, newItem, window = bot.inventory)
  Writes the slot in the local copy only: window.updateSlot(slotId, newItem), then emits
  'heldItemChanged' and 'setSlot:ID'. It sends nothing to the server.
bot._syncWindow(window) -> Promise
  On 1.16.1 it returns at once and does nothing.
