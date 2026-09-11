"""Readable descriptions and bounded excerpts from provider HTML."""
import re
from html.parser import HTMLParser


class _TextParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.hidden += 1
        elif tag in ("p", "div", "br", "li", "tr", "td", "th", "h1", "h2", "h3", "h4", "h5", "h6", "section"):
            self.handle_data("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.hidden = max(0, self.hidden - 1)
        else:
            self.handle_starttag(tag, [])

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def plain_text(value: str | None) -> str | None:
    if value is None:
        return None
    parser = _TextParser()
    parser.feed(value)
    parser.close()
    return "\n".join(filter(None, (" ".join(line.split()) for line in "".join(parser.parts).splitlines())))


def excerpt(value: str | None, query: str, limit: int = 320) -> str:
    text = " ".join((plain_text(value) or "").split())
    terms = [re.escape(term.strip('"')) for term in query.split() if term.strip('"')]
    match = re.search("|".join(terms), text, re.I) if terms else None
    start = max(0, match.start() - 80) if match else 0
    end = start + limit - (1 if start else 0)
    if end < len(text):
        end -= 1
        return ("…" if start else "") + text[start:end].rstrip() + "…"
    return ("…" if start else "") + text[start:end]
