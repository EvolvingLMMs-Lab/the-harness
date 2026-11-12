"""The web from a program: read a page, search.

fetch reads from the kernel itself, so it goes by the user's approvals like any connection
a program makes (runtime/safety/permissions.py). search is the conversation's: it asks the
host, which holds the key of the search it is configured with (runtime.search)."""

from html.parser import HTMLParser
import re
import urllib.request

from harness.runtime.execution import control

# The most characters of a page one call gives, and the most bytes it reads of one.
PAGE_CHARS, PAGE_BYTES = 100_000, 10 * 1024 * 1024
_SKIPPED = frozenset(("script", "style", "noscript", "template", "svg", "head"))
_BREAKS = frozenset(("p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "pre", "section", "article",
                     "table", "ul", "ol", "blockquote"))


class _Text(HTMLParser):
    """A page's text: what its elements show, a line for each block, links with their address."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.skipping, self.link = [], 0, None

    def handle_starttag(self, tag, attributes):
        if tag in _SKIPPED:
            self.skipping += 1
        elif tag in _BREAKS:
            self.parts.append("\n")
        elif tag == "a":
            self.link = dict(attributes).get("href")

    def handle_endtag(self, tag):
        if tag in _SKIPPED:
            self.skipping = max(0, self.skipping - 1)
        elif tag in _BREAKS:
            self.parts.append("\n")
        elif tag == "a":
            if self.link and self.link.startswith(("http://", "https://")):
                self.parts.append(f" ({self.link})")
            self.link = None

    def handle_data(self, data):
        if not self.skipping:
            self.parts.append(data)


def page_text(body: str, kind: str) -> str:
    """The text of a response: an HTML page as its text, anything else as it is."""
    if "html" not in kind and not re.match(r"\s*<(!doctype|html)", body[:200], re.I):
        return body
    parser = _Text()
    parser.feed(body)
    text = re.sub(r"[ \t\r\f\v]+", " ", "".join(parser.parts))
    return re.sub(r"\n\s*\n\s*", "\n\n", re.sub(r" ?\n ?", "\n", text)).strip()


class Web:
    def fetch(self, url, start=0):
        """The text of the page at `url` (http or https): an HTML page as its text with the
        addresses of its links, anything else as it is; at most 100000 characters from
        character `start`, then how to read on."""
        url = str(url).strip()
        if not url.startswith(("http://", "https://")):
            raise ValueError("fetch takes an http or https address")
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; the-harness)",
                                                       "Accept": "text/html,text/plain,application/json,*/*"})
        with urllib.request.urlopen(request, timeout=30) as response:
            kind = (response.headers.get_content_type() or "").lower()
            raw = response.read(PAGE_BYTES + 1)
            charset = response.headers.get_content_charset() or "utf-8"
        if not (kind.startswith("text/") or any(word in kind for word in ("json", "xml", "javascript", "html"))):
            raise ValueError(f"{url} is {kind or 'of an unknown type'} ({len(raw)} bytes), not text")
        try:
            body = raw[:PAGE_BYTES].decode(charset, errors="replace")
        except LookupError:
            body = raw[:PAGE_BYTES].decode("utf-8", errors="replace")
        text = page_text(body, kind)
        start = max(0, int(start))
        more = len(text) - start - PAGE_CHARS
        return text[start:start + PAGE_CHARS] + (
            f"\n... [{more} more characters: fetch(url, start={start + PAGE_CHARS})]" if more > 0 else "")

    def search(self, query, results=5):
        """Search the web for `query`: a list of at most `results` (1 to 10) {"title", "url",
        "text"}. ValueError where the conversation has no search (runtime.search)."""
        query = " ".join(str(query).split())
        if not query:
            raise ValueError("search takes what to search for")
        return control.ask_host("web", action="search", query=query[:400], results=max(1, min(10, int(results))))
