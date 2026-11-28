guide("team"): teams: bot.teams, bot.teamMap, the Team object, the team events.

bot.teams                    object: team name -> Team
bot.teamMap                  object: member name -> Team. A member is a player's username
                             or, for other entities, the string the server lists

Both start empty and change only with the server's teams packets.

Events, by the mode of the packet.
'teamCreated' (team)         mode 0. A new Team is built from the packet, its members are
                             added, and it is stored under its name; a team already
                             stored under that name is replaced
'teamRemoved' (undefined)    mode 1, for a known team. Its members are deleted from
                             bot.teamMap and the team from bot.teams before the event,
                             and the event's argument is undefined
'teamUpdated' (team)         mode 2, for a known team: display name, friendly fire, name
                             tag visibility, collision rule, colour, prefix and suffix
                             are replaced by those of the packet
'teamMemberAdded' (team)     mode 3, for a known team: the packet's players are added
'teamMemberRemoved' (team)   mode 4, for a known team: the packet's players are removed
                             from the team and from bot.teamMap
A packet with mode 1 to 4 for a team name that is not in bot.teams does nothing.
A packet with any other mode number logs the warning 'Unknown team mode handling team
update: undefined' and changes nothing.

Team fields.
team.team                    the team's name, the key in bot.teams (string)
team.name                    ChatMessage, the display name
team.friendlyFire            the number in the packet
team.nameTagVisibility       the string in the packet
team.collisionRule           the string in the packet
team.color                   a string from the formatting number of the packet:
                             0 'black', 1 'dark_blue', 2 'dark_green', 3 'dark_aqua',
                             4 'dark_red', 5 'dark_purple', 6 'gold', 7 'gray',
                             8 'dark_gray', 9 'blue', 10 'green', 11 'aqua', 12 'red',
                             13 'light_purple', 14 'yellow', 15 'white', 16 'obfuscated',
                             17 'bold', 18 'strikethrough', 19 'underlined', 20 'italic',
                             21 'reset'; -1, a number over 21, or none gives 'reset'
team.prefix, team.suffix     ChatMessage
team.members                 array of member names
team.membersMap              object: member name -> ''

Team methods.
team.displayName(member) -> ChatMessage
  A copy of team.prefix, followed by the text member in team.color, followed by
  team.suffix. toString() on it gives prefix + member + suffix as plain text.
team.add(name), team.remove(name)    change team.membersMap only; bot.teamMap and the
                                     server are not touched
team.update(name, friendlyFire, nameTagVisibility, collisionRule, formatting, prefix,
            suffix)                  replaces those fields on the object only
team.parseMessage(str) -> ChatMessage    ChatMessage.fromNotch(str)
