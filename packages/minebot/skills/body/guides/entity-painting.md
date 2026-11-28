guide("entity-painting"): paintings: block.painting and the Painting object.

A painting is not put in bot.entities when the server announces it, and no
'entitySpawn' is emitted for it. The bot keeps its own record of paintings, by entity
id and by block position. When the server removes a painting, 'entityGone' is emitted
with a new, empty Entity carrying only the painting's id (name and type undefined).

block.painting
  bot.blockAt(point) sets block.painting to the Painting recorded at that block's
  position, or undefined when there is none. With bot.blockAt(point, false) the field is
  not set.

Painting
  painting.id            number, the painting's entity id
  painting.position      Vec3, the block position the server sent for the painting
  painting.name          the title value the server sent; on 1.16.1 a number
  painting.direction     Vec3, from the direction number the server sent:
                         0 -> (0, 0, -1), 1 -> (-1, 0, 0), 2 -> (0, 0, 1), 3 -> (1, 0, 0)

The record of a painting is added when the server announces the painting. It is removed
when the server removes that entity id, and when a block change or an explosion changes
the type of the block at the painting's position.
