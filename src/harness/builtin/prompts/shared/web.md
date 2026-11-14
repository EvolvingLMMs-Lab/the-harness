
The web.

  fetch(url, start=0)               the text of a page (http, https): an HTML page as
                                    its text with the addresses of its links, anything
                                    else as it is; at most 100000 characters from
                                    character start, then how to read on
  search(query, results=5)          search the web: a list of {"title", "url", "text"},
                                    at most results (1 to 10); ValueError where this
                                    conversation has no search
