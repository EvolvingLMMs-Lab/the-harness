guide("book"): writing and signing a book and quill: bot.writeBook, bot.signBook.

bot.writeBook(slot, pages) -> Promise<void>
  Writes pages into the book and quill (writable_book) in that slot. The book stays a
  book and quill.
bot.signBook(slot, pages, author, title) -> Promise<void>
  Writes pages and signs the book with that author and title.
  slot: a slot number of the inventory window (bot.inventory): 9 to 35 the inventory,
    36 to 44 the hotbar. The slot of an Item from bot.inventory.items() is such a number.
  pages: an array of strings, one string for each page.
  author, title: strings.

Steps (both).
  1. slot below 0 or above 44: rejects with an AssertionError 'slot out of inventory
     range'. The off hand (45) is outside the range.
  2. bot.inventory.slots[slot] is empty or is not a writable_book: rejects with an
     AssertionError 'no book found in slot S'.
  3. slot below 36: bot.moveSlotItem(slot, 36) moves the book to the first hotbar slot:
     a left-click on slot, a left-click on 36, and, when 36 held an item, a left-click
     on slot that puts that item where the book was. Then the first hotbar slot is
     selected (bot.setQuickBarSlot(0)).
     slot 36 to 44: the book is not moved; hotbar slot slot - 36 is selected.
  4. The code writes the pages (for signBook also author and title) into its own copy of
     the book item and sends one edit-book packet for the main hand, with signing false
     (writeBook) or true (signBook).
  5. It waits for the server to write the book's slot in bot.inventory, 20 seconds at
     most. writeBook: the write counts when the new item has pages. signBook: the write
     counts when the new item is a written_book. Other writes of the slot are passed
     over.
  6. It selects the hotbar slot that was selected before the call, and, when the book
     was moved in step 3, bot.moveSlotItem(36, slot) moves it back.
  7. Resolves with undefined.

Rejections after step 2.
  'Event updateSlot:S did not fire within timeout of 20000ms' (S is 36 when the book was
    moved, else slot): no counting write within 20 seconds. The hotbar selection is not
    restored and the book is not moved back.
  "Server didn't respond to transaction for clicking on slot S on window with id W.":
    one click got no answer within 5 seconds.
  'Server rejected transaction for clicking on slot S, on window with id W.'

The code checks no limit on the number of pages, the length of a page or the length of
the title.
While another window is open (bot.currentWindow), the clicks of steps 3 and 6 go to that
window's slots.
