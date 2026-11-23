guide("title"): the events emitted when the server sends a title to the screen.

On 1.16.1 the server sends one title packet with an action number 0 to 5.

'title' (text, type)
  Action 0: type is 'title'. Action 1: type is 'subtitle'.
  text: a string made from the packet's text. The text is parsed as JSON. A JSON string
  gives that string. A JSON object gives its 'text' field; when that field is missing or
  empty (a translation, or a component made only of children), text is the whole raw
  JSON string. Text that is not JSON is returned with one leading and one trailing '"'
  removed.

'title_times' (fadeIn, stay, fadeOut)
  Action 3: the three integers of the packet, in game ticks.
  Action 2: the packet holds a text and no times; the event is emitted with three
  undefined values and the text is dropped.

'title_clear' ()
  Action 4.

Action 5 emits nothing.
