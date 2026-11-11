"""The agent's text in the chat: Markdown in which what looks like HTML stays text."""

import re

from markdown_it import MarkdownIt
from markdown_it.token import Token
from rich.markdown import Markdown

# A terminal shows no HTML, and rich leaves out what it reads as HTML: each tag (`Vec<String>`
# read `Vec`) and a block that a line starting with a tag opens (`<div>…`), with every line
# up to the next blank one. So HTML is read as text here, but for the two tags that mean
# something in a terminal: a line break, and a key (rich's own style for <kbd>).
PARSER = MarkdownIt("commonmark", {"html": False}).enable("strikethrough").enable("table")
TAGS = re.compile(r"(<br\s*/?>|</?kbd>)", re.IGNORECASE)


class Answer(Markdown):
    def __init__(self, markup: str, **options):
        super().__init__("", **options)
        self.markup = markup
        self.parsed = [_tags(token) for token in PARSER.parse(markup)]


def _tags(token: Token) -> Token:
    if token.children:
        children, keys = [], 0
        for piece in (piece for child in token.children for piece in _pieces(child)):
            if piece.type == "html_inline" and piece.tag == "kbd":
                if piece.content == "<kbd>":
                    keys += 1
                elif keys:
                    keys -= 1
                else:  # a key closed that was not opened: rich would fail on it
                    piece = Token("text", "", 0, content=piece.content)
            children.append(piece)
        token.children = children
    return token


def _pieces(token: Token) -> list:
    if token.type != "text" or "<" not in token.content:
        return [token]
    pieces = []
    for part in TAGS.split(token.content):
        if TAGS.fullmatch(part):
            tag = part.lower()
            pieces.append(Token("hardbreak", "br", 0) if tag.startswith("<br")
                          else Token("html_inline", "kbd", 0, content=tag))
        elif part:
            pieces.append(Token("text", "", 0, content=part))
    return pieces
