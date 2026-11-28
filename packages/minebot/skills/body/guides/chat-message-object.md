guide("chat-message-object"): the ChatMessage object: reading it as text, its fields.

Chat events, boss bar titles, team names and the player list header carry ChatMessage
objects.

A ChatMessage is one text component of the game: a piece of text or a translation key,
its formatting, and a list of child components that follow it.

Reading it as text.
msg.toString() -> string
  The plain text: this component's text, then every child's text, in order. A
  translation key is looked up in bot.registry.language and its %s and %1$s places are
  filled with the texts of msg.with; a key that is not in the table is used as the
  format itself. Colour codes (§ and one character) are removed. The result is cut at
  4096 characters. Children deeper than 8 levels give ''.
  A selector or keybind component gives its raw string; a score component gives
  '<score:NAME:OBJECTIVE>'.
msg.toMotd() -> string     the same text with § colour and style codes kept; a hex colour
                           gives '§#RRGGBB'
msg.toAnsi() -> string     the toMotd text with terminal escape codes in place of § codes
msg.toHTML() -> string     nested <span style="..."> elements, text escaped; over 4096
                           characters it returns the escaped plain text
msg.valueOf()              msg.toString()
msg.getText(index) -> string
  Without a number: msg.toString(). With 0 on a component that has text: that text
  without colour codes. On a component with a translation: the text of msg.with[index],
  then of the children. On a text component with any other index it throws a TypeError.
msg.length() -> number     1 for own text, or the number of msg.with entries, plus the
                           number of children

Fields.
msg.json                   the raw component as the server sent it (a plain object)
msg.text                   own text (string or number); absent on a translation
msg.translate              the translation key, for example 'chat.type.text'; absent
                           on a text component
msg.with                   array of ChatMessage: the arguments of the translation. For
                           'chat.type.text', with[0] is the speaker, with[1] the line
msg.extra                  array of ChatMessage: the children; absent when there are none
msg.color                  a colour name ('red', 'dark_aqua', ...), '#RRGGBB', null, or
                           undefined when the component sets none
msg.bold, msg.italic, msg.underlined, msg.strikethrough, msg.obfuscated
                           as in the component: true, false or undefined
msg.reset                  true when the colour field was 'reset'
msg.clickEvent             { action, value } when present; action is 'open_url',
                           'open_file', 'run_command' or 'suggest_command'
msg.hoverEvent             { action, value | contents } when present. For 'show_item'
                           the value is parsed into an NBT object when it parses
msg.selector, msg.keybind, msg.score, msg.fallback    set when the component has them

Changing and copying.
msg.append(...parts)       adds children: a ChatMessage is added as it is, a string is
                           turned into a ChatMessage first. msg.json is not changed
msg.clone() -> ChatMessage a new object built from a copy of msg.json

Building one.
ChatMessage = msg.constructor
new ChatMessage(value)
  value a string: text with § codes is split into coloured parts; '' gives empty text.
  A number: that number as text. An array: the children of an empty component. An
  object: a component. Any other type throws 'Expected String or Object for Message
  argument'. A 'with' or 'extra' field that is not an array throws 'Expected with
  property to be an Array in ChatMessage' / 'Expected extra property to be an Array in
  ChatMessage'. A clickEvent or hoverEvent without a string action throws 'ClickEvent
  action missing in ChatMessage' / 'HoverEvent action missing in ChatMessage'.
ChatMessage.fromNotch(str) -> ChatMessage
  Parses str as JSON and builds from the result; when it is not JSON, builds from the
  string itself.
ChatMessage.fromNetwork(type, params)    on 1.16.1 throws a TypeError: the chat format
                                         table it reads is absent
ChatMessage.MessageBuilder               a builder class with setText, setColor, setBold,
                                         addExtra, toJSON and the like
