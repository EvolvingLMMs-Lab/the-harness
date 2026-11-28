guide("hand-held-item"): the held item, the selected hotbar slot, and the
'heldItemChanged' event.

bot.heldItem                         Item | null, read-only getter
  Returns bot.inventory.slots[36 + bot.quickBarSlot]: the item in the selected hotbar
  slot, or null when that slot is empty. While bot.quickBarSlot is still null it returns
  slot 36. It reads bot.inventory also while another window is open; in that time
  bot.inventory does not follow the open window (see guide("inventory-updates")).

bot.quickBarSlot                     number 0 to 8, or null
  The selected hotbar slot. null until the server's first held-item-slot packet. Each
  held-item-slot packet from the server goes through bot.setQuickBarSlot(packet.slot).
  Writing the property directly changes what bot.heldItem returns and sends nothing.

bot.QUICK_BAR_START                  36: the bot.inventory slot number of hotbar slot 0

bot.setQuickBarSlot(slot)
  Synchronous; returns nothing. slot below 0, 9 or more, or not a number: AssertionError.
  When slot equals bot.quickBarSlot it does nothing. Otherwise it sets bot.quickBarSlot,
  sends a held-item-slot packet with that slot, and emits 'heldItemChanged'. It does not
  wait for the server and does not look at whether a window is open.

bot.updateHeldItem()
  Emits 'heldItemChanged' with bot.heldItem. It changes nothing.

bot 'heldItemChanged' (heldItem)
  The argument is bot.heldItem at that moment (Item or null). It is emitted:
  - by bot.setQuickBarSlot when the slot changes;
  - when the selected hotbar slot of bot.inventory is written (any 'updateSlot' of slot
    36 + bot.quickBarSlot), also when the new item equals the old one;
  - after every set-slot packet that is applied, for any slot of any window;
  - after every window-items packet that is applied, and when a window opens with its
    items already received;
  - after every server answer to a click made with bot.clickWindow, accepted or rejected;
  - by bot.moveSlotItem after its second click.
  So the event also fires when the held item is the same as before.

What the event does inside the library.
  Each 'heldItemChanged' emitted while bot.heldItem is an item (not null) ends a running
  bot.consume() (it resolves) and sets bot.usingHeldItem to false. The handler compares
  the new item with a stored previous item, and that stored item stays null, so every
  event with an item in the hand counts as a change. An event with an empty hand does
  neither.

bot.equip(item, 'hand') and bot.unequip('hand') change the held item; they are in
guide("equip").
