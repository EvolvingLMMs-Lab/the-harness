guide("weather"): bot.isRaining, bot.rainState, bot.thunderState and their events.

bot.isRaining                        boolean, false at creation
bot.rainState                        number, 0 at creation: the rain level the server sent
bot.thunderState                     number, 0 at creation: the thunder level the server
                                     sent
  All three are set from the server's game state packets only. They are not reset at
  login or at a change of dimension.

What each packet does.
  'start raining'        bot.isRaining = true; 'rain' is emitted when it was false
  'stop raining'         bot.isRaining = false; 'rain' is emitted when it was true
  'rain level change'    bot.rainState = the packet's value; 'weatherUpdate' is emitted;
                         then, when the level went from 0 to above 0 or back, bot.isRaining
                         is set to (value > 0), with 'rain' when that changes it
  'thunder level change' bot.thunderState = the packet's value; 'weatherUpdate' is emitted

Events.
  'rain' ()            bot.isRaining changed
  'weatherUpdate' ()   bot.rainState or bot.thunderState was set, also to the same value

Used by another call.
  bot.sleep counts a thunderstorm as bot.isRaining true and bot.thunderState above 0:
  guide("bed").
