guide("tablist"): the header and footer of the player list.

bot.tablist                  { header, footer }
bot.tablist.header           ChatMessage; bot.tablist.header.toString() is its plain text
bot.tablist.footer           ChatMessage

Both start as an empty ChatMessage (toString() gives '').
The server's playerlist_header packet replaces them. A header or footer that is an empty
string in the packet leaves the stored one as it was. Line breaks inside the text are
kept: the text of a header with two lines has a '\n' in it.
No event is emitted when they change.

The entries of the player list are in bot.players.
