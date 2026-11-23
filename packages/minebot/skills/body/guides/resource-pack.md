guide("resource-pack"): answering the server's offer of a resource pack.

'resourcePack' (url, hash)
  Emitted when the server sends a resource pack offer. url and hash are the two strings
  of the packet. The bot sends no answer on its own.

bot.acceptResourcePack() -> undefined
  Writes two resource_pack_receive packets: result 3 (accepted), then result 0 (loaded).
  Nothing is downloaded. The call waits for nothing and can be made at any time, with or
  without an offer.

bot.denyResourcePack() -> undefined
  Writes one resource_pack_receive packet with result 1 (declined).
