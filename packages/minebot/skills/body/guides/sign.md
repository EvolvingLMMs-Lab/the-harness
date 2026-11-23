guide("sign"): writing a sign, reading its text, and the sign events.

bot.updateSign(block, text, back = false)
  Sends the text of a sign to the server. block: the sign's Block (its position is read).
  text: a string; lines are separated by '\n'.
  More than 4 lines: emits 'error' on bot with 'too many lines for sign text' and sends
  nothing.
  A line longer than 45 characters: emits 'error' on bot with 'Signs have a maximum of 45
  characters per line' and sends nothing.
  Otherwise it sends the position and four lines (missing lines as ''), as plain text.
  back has no effect on this version.
  It returns undefined at once. It waits for no answer and does not check that the block
  is a sign or that the server has opened the sign for editing.

'signOpen' (block)                event on bot
  The server tells the bot to open the editor of a sign. block is
  bot.blockAt(position): null when the column is not loaded.

'blockEntityData' (block)         event on bot
  The server sent the data of a block entity, a sign's text among them. block is
  bot.blockAt(position) with the new data.

Reading. A Block whose name contains 'sign' has these; other blocks do not.
block.getSignText() -> [string]
  An array with one string: the four lines as plain text joined with '\n', with
  whitespace at the end removed. [''] when the block has no block entity data
  (block.entity undefined). With block entity data that lacks one of the four text
  fields it throws a TypeError.
block.signText                    getter: block.getSignText()[0]
  The text comes from the block entity data in the bot's copy: what the server sent with
  the column or in a later block entity message.

Writing into a Block object.
block.setSignText(front)
  front: a string (lines separated by '\n') or an array of lines (strings, objects, or
  chat messages). It writes the lines into block.entity of that object, creating it when
  absent. Nothing is sent to the server and the bot's copy of the world is unchanged.
  A second argument that is not undefined throws 'Cannot set the back text of a sign on
  a version before 1.20 : 1.16.1'.
block.signText = text             setter: block.setSignText(text)
