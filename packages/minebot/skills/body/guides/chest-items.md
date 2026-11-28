guide("chest-items"): the members of an open container window and where each is described.

bot.openContainer (guide("chest")) resolves with the Window that bot.openBlock or
bot.openEntity gives; it adds no member to it. N is window.inventoryStart: the number of
container slots.

Methods and fields of every Window: guide("window-object").
window.containerItems() -> [Item]     the items in slots 0 to N-1 (the container)
window.items() -> [Item]              the items in slots N to N+35 (the bot's inventory)
window.containerCount(itemType, metadata) -> number   items of that id in the container
window.count(itemType, metadata) -> number            items of that id in the inventory part
window.slots                          array of Item or null, indexed by slot

Calls added to every opened window: guide("window-open-close").
window.deposit(itemType, metadata, count, nbt) -> Promise<void>
  Moves count items of that id from the inventory part (N to N+35) to the container
  (0 to N-1).
window.withdraw(itemType, metadata, count, nbt) -> Promise<void>
  Moves count items of that id from the container to the inventory part.
window.close() -> Promise<void>
  Closes the window and emits 'close' on it.

Events of the window: guide("window-object-changes").
  'updateSlot' (slot, oldItem, newItem)    a slot of this window was written: by a packet
                                           of the server, or by the result of a click
  'updateSlot:S' (oldItem, newItem)        the same, for slot S only
  'close' ()                               emitted by window.close()
Events of the bot: guide("window-open-close").
  'windowOpen' (window)     the server opened a window and its items have arrived
  'windowClose' (window)    window.close() or bot.closeWindow was called, or the server
                            closed the window
