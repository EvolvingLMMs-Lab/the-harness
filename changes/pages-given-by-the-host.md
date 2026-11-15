---
---
`guide(name)` no longer returns the page to the program that calls it. It asks for the page:
the host puts the whole page into the model's next message, and the page counts as read from
that message on, as Claude Code counts a file as read when its Read tool returned it. The
call returns one line that says so. A call that waits for a page (a skill's `before`,
`set_reflex` for "tree") is refused until then, so a page is asked for in one program and
used in a later one. One message carries pages up to 100,000 characters; a page asked for
beyond that is not given and not read, and the returned line says so.
