"""Strict structural audit for this generator's HTML dialect (stdlib only).

This is a generator contract check, not a general-purpose HTML sanitizer.
"""

from html.parser import HTMLParser
from pathlib import Path
import re


ALLOWED = {
    "html": {"lang"}, "head": set(), "meta": {"charset", "name", "content", "http-equiv"},
    "title": set(), "style": set(), "body": set(),
    "main": {"class", "role", "aria-label"}, "div": {"class", "style", "aria-hidden"},
}
VOID = {"meta"}


class ContractParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.errors = []
        self.stack = []
        self.styles = []
        self.shapes = 0
        self.mains = 0
        self.has_csp = False

    def handle_decl(self, decl):
        if decl.lower() != "doctype html":
            self.errors.append("Unexpected document declaration")

    def handle_starttag(self, tag, attrs):
        if tag not in ALLOWED:
            self.errors.append(f"Forbidden element: {tag}")
        values = dict(attrs)
        if len(values) != len(attrs):
            self.errors.append(f"Duplicate attributes on {tag}")
        for name, value in attrs:
            if name not in ALLOWED.get(tag, set()):
                self.errors.append(f"Forbidden attribute: {tag}.{name}")
            if name == "style":
                self.styles.append(value or "")
        if tag == "meta":
            if values.get("http-equiv", "").lower() == "content-security-policy":
                policy = values.get("content", "")
                self.has_csp = all(part in policy for part in ("default-src 'none'", "script-src 'none'", "img-src 'none'"))
            elif "http-equiv" in values:
                self.errors.append("Only the Content-Security-Policy http-equiv is permitted")
        if tag == "main":
            self.mains += 1
        if tag == "div":
            classes = (values.get("class") or "").split()
            for token in classes:
                if not re.fullmatch(r"shape|underpainting|p\d+", token):
                    self.errors.append(f"Unexpected class token: {token}")
            if "shape" in classes:
                self.shapes += 1
                if "clip-path:polygon(" not in values.get("style", ""):
                    self.errors.append("Shape lacks a CSS polygon")
        if tag not in VOID:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if not self.stack or self.stack[-1] != tag:
            self.errors.append(f"Unbalanced closing tag: {tag}")
        else:
            self.stack.pop()

    def handle_data(self, data):
        if self.stack and self.stack[-1] == "style":
            self.styles.append(data)
        elif self.stack and self.stack[-1] != "title" and data.strip():
            self.errors.append("Unexpected visible text outside the title")


def audit_html(document: str):
    parser = ContractParser()
    parser.feed(document)
    parser.close()
    errors = parser.errors
    if parser.stack:
        errors.append("Unclosed elements")
    if parser.mains != 1:
        errors.append("Expected exactly one illustration main")
    if not parser.has_csp:
        errors.append("Missing restrictive Content-Security-Policy")
    css = "\n".join(parser.styles)
    # Generated CSS never uses comments or escape sequences. Reject them rather
    # than trying to interpret obfuscated external resource or script syntax.
    if "\\" in css or "/*" in css:
        errors.append("CSS escapes/comments are outside the generator contract")
    for pattern in (r"url\s*\(", r"@import\b", r"base64", r"data\s*:", r"expression\s*\(", r"javascript\s*:"):
        if re.search(pattern, css, re.IGNORECASE):
            errors.append(f"Forbidden CSS construct: {pattern}")
    return {"valid": not errors, "errors": sorted(set(errors)), "shapes": parser.shapes,
            "gradient_fills": css.count("linear-gradient("), "bytes": len(document.encode("utf-8"))}


def audit_file(path: Path):
    text = path.read_text(encoding="utf-8")
    if re.search(r"<svg\b", text, re.IGNORECASE):
        return audit_svg(text)
    return audit_html(text)


# --- SVG dialect contract ---------------------------------------------------

ALLOWED_SVG = {
    "html": {"lang"}, "head": set(), "meta": {"charset", "name", "content", "http-equiv"},
    "title": set(), "style": set(), "body": set(),
    "main": {"class", "role", "aria-label"},
    "svg": {"viewbox", "xmlns", "role", "aria-hidden", "width", "height", "preserveaspectratio"},
    "defs": set(), "lineargradient": {"id", "gradientunits", "x1", "y1", "x2", "y2"},
    "radialgradient": {"id", "gradientunits", "cx", "cy", "r"},
    "stop": {"offset", "stop-color"}, "path": {"d", "fill", "fill-rule", "clip-path"},
    "g": {"clip-path", "id", "class", "data-color"}, "clippath": {"id"},
}
# SVG elements that must never appear: images, scripts, foreign/object embedding.
FORBIDDEN_SVG = {
    "img", "script", "canvas", "iframe", "object", "embed", "a", "link",
    "use", "image", "foreignobject", "text", "tspan", "animate", "audio", "video",
}
VOID_SVG = {"meta"}


class ContractParserSvg(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.errors = []
        self.stack = []
        self.styles = []
        self.shapes = 0
        self.gradient_fills = 0
        self.mains = 0
        self.has_csp = False

    def handle_decl(self, decl):
        if decl.lower() != "doctype html":
            self.errors.append("Unexpected document declaration")

    def handle_starttag(self, tag, attrs):
        key = tag.lower()
        if key in FORBIDDEN_SVG:
            self.errors.append(f"Forbidden element: {tag}")
        if key not in ALLOWED_SVG:
            self.errors.append(f"Forbidden element: {tag}")
        values = dict(attrs)
        if len(values) != len(attrs):
            self.errors.append(f"Duplicate attributes on {tag}")
        for name, value in attrs:
            low = name.lower()
            if low not in ALLOWED_SVG.get(key, set()):
                self.errors.append(f"Forbidden attribute: {tag}.{name}")
            if low == "style":
                self.styles.append(value or "")
            if low in ("fill", "clip-path", "stop-color", "d") and value is not None:
                scanned = value
                for token in (r"url\s*\(\s*(?!\s*#)", r"javascript\s*:", r"data\s*:", r"base64"):
                    if re.search(token, scanned, re.IGNORECASE):
                        self.errors.append(f"Forbidden resource reference in {tag}.{name}")
        if key == "meta":
            if values.get("http-equiv", "").lower() == "content-security-policy":
                policy = values.get("content", "")
                self.has_csp = all(part in policy for part in ("default-src 'none'", "script-src 'none'", "img-src 'none'"))
            elif "http-equiv" in values:
                self.errors.append("Only the Content-Security-Policy http-equiv is permitted")
        if key == "main":
            self.mains += 1
        if key == "path":
            if "fill" in values:
                self.shapes += 1
                if values["fill"].startswith("url(#"):
                    self.gradient_fills += 1
        if key not in VOID_SVG:
            self.stack.append(key)

    def handle_endtag(self, tag):
        key = tag.lower()
        if not self.stack or self.stack[-1] != key:
            self.errors.append(f"Unbalanced closing tag: {tag}")
        else:
            self.stack.pop()

    def handle_data(self, data):
        if self.stack and self.stack[-1] == "style":
            self.styles.append(data)
        elif self.stack and self.stack[-1] != "title" and data.strip():
            self.errors.append("Unexpected visible text outside the title")


def audit_svg(document: str):
    parser = ContractParserSvg()
    parser.feed(document)
    parser.close()
    errors = parser.errors
    if parser.stack:
        errors.append("Unclosed elements")
    if parser.mains != 1:
        errors.append("Expected exactly one illustration main")
    if not parser.has_csp:
        errors.append("Missing restrictive Content-Security-Policy")
    css = "\n".join(parser.styles)
    if "\\" in css or "/*" in css:
        errors.append("CSS escapes/comments are outside the generator contract")
    for pattern in (r"url\s*\(", r"@import\b", r"base64", r"data\s*:", r"expression\s*\(", r"javascript\s*:"):
        if re.search(pattern, css, re.IGNORECASE):
            errors.append(f"Forbidden CSS construct: {pattern}")
    return {"valid": not errors, "errors": sorted(set(errors)), "shapes": parser.shapes,
            "gradient_fills": parser.gradient_fills, "bytes": len(document.encode("utf-8"))}
