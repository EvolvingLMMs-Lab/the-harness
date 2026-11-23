guide("window-click"): bot.clickWindow: sending one click, its confirmation, time limits
and errors.

bot.clickWindow(slot, mouseButton, mode) -> Promise
  Clicks in bot.currentWindow, or in bot.inventory when no window is open. slot is a slot
  number of that window, or -999 for outside the window. mode is 0 to 6:
    0  plain click: mouseButton 0 left, 1 right
    1  shift click: mouseButton 0 or 1
    2  number key: mouseButton 0 to 8 is the hotbar slot to swap with
    3  middle click: mouseButton 2
    4  drop key: mouseButton 0 drops one item of the slot, 1 the whole stack
    5  drag, 6 double click: the local window code does not implement them
  What each mode does to the slots is in guide("window-click-modes").

  Steps:
  1. When slot is 36 or more and the bot has dug before: it waits until 500 ms have
     passed since bot.lastDigTime.
  2. mode outside 0 to 6: AssertionError.
  3. It takes the next action number (1 to 32767, then 1 again) and records the click
     with the item now in that slot.
  4. It sends one window-click packet: window id, slot, mouseButton, the action number,
     mode, and the item in the slot (an empty item for modes 1, 2 and 4).
  5. It waits for the server's transaction packet with that action number, 5000 ms at
     most. The local slots are not changed before that packet.
  6. Accepted: the click is applied to the window's slots and cursor, 'heldItemChanged'
     is emitted, and the promise resolves with nothing.
     Rejected: the bot answers the server with a transaction packet, the local slots stay
     as they were, 'heldItemChanged' is emitted, and the promise rejects. The game then
     sends every slot of the window and what is on the cursor, and both are written to
     the local copy. A refusal in the middle of a move of several clicks (bot.equip,
     bot.transfer) leaves the item that was picked up on the cursor:
     window.selectedItem holds it, and it is in no slot.
     Measured in the game: a click on a stack sent at once after the stack changed (a
     block placed from it, a block dug with it) was refused 1 time in 16; sent 300 ms
     later, 0 times in 16.

  Rejects with:
  - 'Server rejected transaction for clicking on slot S, on window with id W.'
  - "Server didn't respond to transaction for clicking on slot S on window with id W."
    after 5000 ms without an answer. This also happens when the clicked window is no
    longer the open one when the answer comes (the answer is then dropped), and when the
    local window code cannot apply the click.
  Clicks are confirmed in the order sent. A confirmation for a later action number
  applies all earlier unconfirmed clicks as accepted first.

  Clicks the local window code refuses (when the server accepts one, the code throws an
  AssertionError 'invalid operation' or 'unimplemented' inside the packet handler, and
  no confirmation reaches the promise): a slot that is not -999 and not below
  window.inventoryEnd (slot 45 is allowed in bot.inventory); a mouseButton outside the
  list for the mode; modes 5 and 6.
  Mode 0 with mouseButton 1 on slot -999 with an empty cursor throws a TypeError there.

bot.simpleClick.leftMouse(slot) -> Promise      bot.clickWindow(slot, 0, 0)
bot.simpleClick.rightMouse(slot) -> Promise     bot.clickWindow(slot, 1, 0)

window.selectedItem                  the Item on the cursor of that window, or null
  Each window has its own. A left click on a stack puts it there; guide("window-object").

bot 'confirmTransaction<N>' (success)
  Emitted for the click with action number N: true when accepted, false when rejected.
A transaction packet from the server that matches no pending click is answered with a
transaction packet and changes nothing.

Built on clickWindow: bot.transfer, bot.putAway, bot.moveSlotItem,
bot.putSelectedItemRange in guide("window-transfer"); bot.equip, bot.unequip in
guide("equip"); bot.toss, bot.tossStack in guide("toss").
