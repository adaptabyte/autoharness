"""Docs for an app: a manual, a list of keyboard shortcuts, a picture of the controls, a web page about it.

Give them to `autoharness teach --docs` and Muse Wonder reads all of them once, before anything touches the app. It then
writes Muse Spark a short brief: the controls, how the docs say the job is done, and what to check on the screen first.
So Spark checks what the docs say instead of pressing every key to find out. Wonder gets the brief again when it writes
the plan or program, next to what Spark actually saw.

The docs are never taken on trust. They may describe another version of the app, so the screen wins whenever the two
disagree. As always, a plan or program is kept only after it passes its runs on its own.
"""
from __future__ import annotations

import io
import re
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path

import numpy as np
from PIL import Image

from . import config
from .cloud import Cloud, Meter, image_url, response_text
from .local import extract_json

MAX_BYTES = 40_000_000
MAX_CHARS = 160_000  # about 40,000 tokens, so reading costs Wonder about $0.16 at most
MAX_PICTURES = 12
PICTURES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
TEXTS = {".txt", ".md", ".markdown", ".rst", ".adoc", ".org", ".csv", ".tsv", ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".xml", ".log"}
PAGES = {".html", ".htm", ".xhtml"}
READABLE = PICTURES | TEXTS | PAGES | {".pdf", ".docx"}
WHAT_IT_READS = "PDFs, pictures, web pages, Word files and text files"


class DocsError(ValueError):
    pass


@dataclass
class Doc:
    name: str
    kind: str  # PDF, picture, web page, Word file or text
    text: str = ""
    pictures: list = field(default_factory=list)  # RGB arrays, with a caption each
    captions: list = field(default_factory=list)
    detail: str = ""
    links: list = field(default_factory=list)  # a web page's links, to read the rest of a docs site

    def label(self) -> str:
        return f"{self.name} ({', '.join(x for x in (self.kind, self.detail) if x)})"


# ---- Reading --------------------------------------------------------------------------------------------------------------

def read(sources: list[str]) -> list[Doc]:
    """Files, folders and web addresses, each read into text and pictures. Anything that can't be read is an error now,
    before any money is spent, never a document quietly left out."""
    docs: list[Doc] = []
    for s in sources:
        s = str(s).strip()
        if not s:
            continue
        if s.lower().startswith("docsdb:"):
            from .guides import shared_url, slug
            s = shared_url(slug(s.split(":", 1)[1]))  # a guide someone shared, by its name
        if re.match(r"https?://", s, re.I):
            doc = from_url(s)
            m = re.search(r"/docsdb/([a-z0-9-]+)/SKILL\.md$", s)
            if m:
                doc.name, doc.kind = f"the docsdb guide to {m.group(1)}", "shared, reviewed"
            docs.append(doc)
            continue
        path = Path(s).expanduser()
        if path.is_dir():
            found = files_in(path)
            if not found:
                raise DocsError(f"{s} has no {WHAT_IT_READS} in it")
            docs.extend(from_file(f) for f in found)
        elif path.is_file():
            doc = from_file(path)
            if path.name == "SKILL.md" and path.parent.parent.name == "guides":
                doc.name, doc.kind = f"your guide to {path.parent.name}", "from earlier lessons"
            docs.append(doc)
        else:
            raise DocsError(f"can't find {s}: give a file, a folder or a web address")
    if not docs:
        raise DocsError("no docs were given")
    return docs


def files_in(folder: Path) -> list[Path]:
    return sorted(p for p in folder.rglob("*") if p.is_file() and p.suffix.lower() in READABLE and not any(x.startswith(".") for x in p.relative_to(folder).parts))


def from_file(path: Path) -> Doc:
    if path.stat().st_size > MAX_BYTES:
        raise DocsError(f"{path.name} is over {MAX_BYTES // 1_000_000} MB")
    return from_bytes(_shown_name(path.name), path.read_bytes())


def _shown_name(name: str) -> str:
    """The web app keeps uploads as <random>-<name>; people should see the name they gave."""
    return re.sub(r"^[0-9a-f]{12}-", "", name)


MAX_LINKED = 24


def _fetch(url: str) -> tuple[bytes, str, str]:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Autoharness reading an app's docs)", "Accept": "*/*"})
    if config.DEMO:
        from .egress import opener  # in the public demo, docs come only from public websites, redirects included
        open_url = opener().open
    else:
        open_url = urllib.request.urlopen
    try:
        with open_url(req, timeout=30) as r:
            data = r.read(MAX_BYTES + 1)
            ctype = (r.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            final = r.geturl()
    except Exception as e:  # noqa: BLE001 - any failure to fetch is the same plain error
        raise DocsError(f"couldn't open {url}: {getattr(e, 'reason', None) or e}") from None
    if len(data) > MAX_BYTES:
        raise DocsError(f"{url} is over {MAX_BYTES // 1_000_000} MB")
    return data, ctype, final


def from_url(url: str, follow: bool = True) -> Doc:
    data, ctype, final = _fetch(url)
    parts = urllib.parse.urlsplit(final)
    name = (parts.netloc + parts.path).rstrip("/")
    name = name if len(name) <= 70 else name[:40] + "..." + name[-27:]
    doc = from_bytes(name, data, ctype)
    if doc.kind == "web page" and len(doc.text) < 600 and not config.DEMO:
        # Many docs sites build the page with JavaScript, so the raw HTML is nearly empty. A real browser sees the text.
        rendered = _rendered_text(final)
        if len(rendered) > len(doc.text):
            doc.text = rendered
    if follow and doc.kind == "web page" and len(doc.text) < 3000:
        # A docs site's front page is mostly a list of contents, so read the pages it lists beside it, one level down.
        pages = beside(final, doc.links)[:MAX_LINKED]
        if pages:
            from concurrent.futures import ThreadPoolExecutor

            def one(u):
                try:
                    return from_url(u, follow=False)
                except DocsError:
                    return None
            with ThreadPoolExecutor(6) as pool:
                got = [d for d in pool.map(one, pages) if d and d.text]
            doc.text += "".join(f"\n\n[page: {d.detail or d.name}]\n{d.text}" for d in got)
            missed = len(pages) - len(got)
            doc.detail = ", ".join(x for x in (doc.detail, f"and {len(got)} pages it links to" + (f", {missed} of which wouldn't open" if missed else "")) if x)
    return doc


def beside(base: str, links: list[str]) -> list[str]:
    """Pages a contents page links to on the same site, under the same folder: the rest of the docs, not the whole web."""
    b = urllib.parse.urlsplit(base)
    folder = b.path[:b.path.rfind("/") + 1]
    seen = {b.path, folder, folder + "index.html"}
    out = []
    for href in links:
        u = urllib.parse.urlsplit(urllib.parse.urljoin(base, href.strip()))
        if (u.scheme, u.netloc) != (b.scheme, b.netloc) or not u.path.startswith(folder) or u.path in seen:
            continue
        if Path(u.path).suffix.lower() not in ("", ".html", ".htm", ".xhtml", ".php", ".aspx", ".md", ".txt"):
            continue
        seen.add(u.path)
        out.append(urllib.parse.urlunsplit((u.scheme, u.netloc, u.path, u.query, "")))
    return out


def _rendered_text(url: str) -> str:
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                page = browser.new_page()
                page.goto(url, timeout=30000, wait_until="networkidle")
                return _tidy(page.inner_text("body"))
            finally:
                browser.close()
    except Exception:  # noqa: BLE001 - no browser here, or the page won't load: keep what plain fetching got
        return ""


def from_bytes(name: str, data: bytes, ctype: str = "") -> Doc:
    suffix = Path(urllib.parse.urlsplit(name).path).suffix.lower()
    if suffix == ".pdf" or ctype == "application/pdf" or data[:5] == b"%PDF-":
        return _pdf(name, data)
    if suffix in PICTURES or ctype.startswith("image/"):
        try:
            img = Image.open(io.BytesIO(data)).convert("RGB")
        except Exception:  # noqa: BLE001
            raise DocsError(f"{name} isn't a picture that can be opened") from None
        return Doc(name, "picture", pictures=[_fit(img)], captions=[name])
    if suffix == ".docx":
        return _docx(name, data)
    text = data.decode("utf-8", "replace")
    if suffix in PAGES or ctype in ("text/html", "application/xhtml+xml") or (not suffix and re.match(r"\s*(<!doctype html|<html)", text[:500], re.I)):
        page = _PageText()
        page.feed(text)
        return Doc(name, "web page", text=_tidy(page.text()), detail=" ".join(page.title.split())[:80], links=page.links)
    if suffix in TEXTS or ctype.startswith("text/") or ctype in ("application/json", "application/xml") or (not suffix and _looks_like_text(data)):
        return Doc(name, "text", text=_tidy(text))
    raise DocsError(f"can't read {name}: it reads {WHAT_IT_READS}")


def _looks_like_text(data: bytes) -> bool:
    sample = data[:4000]
    return b"\x00" not in sample and sample.decode("utf-8", "replace").count("�") < 5


def _fit(img: Image.Image, longest: int = 1600) -> np.ndarray:
    scale = min(1.0, longest / max(img.size))
    if scale < 1:
        img = img.resize((round(img.width * scale), round(img.height * scale)), Image.LANCZOS)
    return np.asarray(img)


def _pdf(name: str, data: bytes) -> Doc:
    import pypdfium2 as pdfium
    try:
        pdf = pdfium.PdfDocument(data)
    except Exception as e:  # noqa: BLE001
        raise DocsError(f"{name} isn't a PDF that can be opened ({e})") from None
    pages, pictures, captions = [], [], []
    for i in range(len(pdf)):
        page = pdf[i]
        text = page.get_textpage().get_text_range().strip()
        pages.append(f"[page {i + 1}]\n{text}")
        # A page that's mostly picture, like a diagram of the controls or a scan, is read as a picture too.
        if len(pictures) < MAX_PICTURES and len(text) < 2500 and _drawn_share(page) > 0.2:
            pictures.append(_fit(page.render(scale=1.6).to_pil().convert("RGB")))
            captions.append(f"{name}, page {i + 1}")
    doc = Doc(name, "PDF", text=_tidy("\n\n".join(pages)), pictures=pictures, captions=captions, detail=f"{len(pdf)} page{'s' if len(pdf) != 1 else ''}")
    pdf.close()
    return doc


def _drawn_share(page) -> float:
    """How much of a page is covered by pictures and drawings, roughly: thin rules and small logos don't count."""
    import pypdfium2.raw as raw
    w, h = page.get_size()
    area, covered = max(w * h, 1.0), 0.0
    for obj in page.get_objects(filter=[raw.FPDF_PAGEOBJ_IMAGE, raw.FPDF_PAGEOBJ_PATH, raw.FPDF_PAGEOBJ_SHADING]):
        left, bottom, right, top = obj.get_bounds()
        part = max(0.0, right - left) * max(0.0, top - bottom) / area
        if part > 0.01:
            covered += part
    return min(covered, 1.0)


def _docx(name: str, data: bytes) -> Doc:
    try:
        xml = zipfile.ZipFile(io.BytesIO(data)).read("word/document.xml").decode("utf8")
    except Exception:  # noqa: BLE001
        raise DocsError(f"{name} isn't a Word file that can be opened") from None
    xml = re.sub(r"</w:p>", "\n", xml)
    xml = re.sub(r"<w:tab/>", "\t", xml)
    text = re.sub(r"<[^>]+>", "", xml)
    import html
    return Doc(name, "Word file", text=_tidy(html.unescape(text)))


class _PageText(HTMLParser):
    """The readable text of a web page: headings, paragraphs, lists, tables and keys, without scripts, styles or menus.
    When the page marks its main content, only that is kept."""
    SKIP = {"script", "style", "noscript", "svg", "template", "nav", "footer"}
    BLOCK = {"p", "div", "section", "article", "main", "br", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "table", "ul", "ol", "dl", "dt", "dd", "pre", "blockquote", "figcaption"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.main: list[str] = []
        self.in_main = 0
        self.skipping = 0
        self.title = ""
        self.in_title = False
        self.links: list[str] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "title":
            self.in_title = True
        if tag == "a" and a.get("href"):
            self.links.append(a["href"])
        if tag in ("main", "article") or a.get("role") == "main":
            self.in_main += 1
        if tag in self.SKIP:
            self.skipping += 1
        elif tag == "li":
            self.parts.append("\n- ")
        elif tag in ("td", "th"):
            self.parts.append(" | ")
        elif tag == "img":
            if a.get("alt"):
                self.add(f" [picture: {a['alt']}] ")
        elif tag in self.BLOCK:
            self.add("\n")

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False
        if tag in self.SKIP:
            self.skipping = max(0, self.skipping - 1)
        elif tag in self.BLOCK:
            self.add("\n")
        if tag in ("main", "article"):
            self.in_main = max(0, self.in_main - 1)

    def add(self, text: str) -> None:
        self.parts.append(text)
        if self.in_main:
            self.main.append(text)

    def handle_data(self, data):
        if self.in_title:
            self.title += data
        elif not self.skipping:
            self.add(data)

    def text(self) -> str:
        main = "".join(self.main)
        return main if len(main.strip()) > 300 else "".join(self.parts)


def _tidy(text: str) -> str:
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"(?m)^[-|]\s*$", "", text)  # bullets and table cells with nothing in them
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def fit(docs: list[Doc], max_chars: int = MAX_CHARS, max_pictures: int = MAX_PICTURES) -> list[str]:
    """Trim the docs to what Wonder reads in one go, shortest kept whole, and say what was cut. Pictures people gave
    come before PDF pages read as pictures."""
    cut = []
    total = sum(len(d.text) for d in docs)
    if total > max_chars:
        share, left = max_chars, len([d for d in docs if d.text])
        for d in sorted((d for d in docs if d.text), key=lambda d: len(d.text)):
            allowed = share // left
            if len(d.text) > allowed:
                cut.append(f"only the first {allowed:,} of {len(d.text):,} characters of {d.name}")
                d.text = d.text[:allowed]
            share -= len(d.text)
            left -= 1
    shown = 0
    for d in sorted(docs, key=lambda d: d.kind != "picture"):
        keep = max(0, min(len(d.pictures), max_pictures - shown))
        if keep < len(d.pictures):
            cut.append(f"{len(d.pictures) - keep} of the pictures in {d.name}")
            d.pictures, d.captions = d.pictures[:keep], d.captions[:keep]
        shown += keep
    return cut


# ---- Wonder's brief for Spark ------------------------------------------------------------------------------------------------

BRIEF_RULES = """Someone wants Autoharness to learn a job in an app, and gave you documents about the app: a manual, \
shortcuts, pictures of the controls, web pages. Next, another model, Muse Spark, will use the real app on a screen to learn \
it, in a limited number of turns. Then you'll write the plan or program a small model runs. Read everything below now, so \
Spark can confirm what the documents say instead of trying every control to find out.

App: {address}
Job: {goal}

Keep only what helps with this job. Write keys, buttons and menus exactly as the documents do. The documents may describe \
another version of the app, so write each point as something to confirm, not as fact. Never add anything the documents \
don't say. Reply with only JSON:
{{"app": "the app's name",
"about": "one or two sentences on what the app is and how it works",
"controls": [{{"input": "a key, button, menu item or gesture, as written", "does": "what it does"}}],
"how_to": ["the steps the documents give for this job, or for the closest thing to it"],
"rules": ["how the app behaves, where it matters for the job: goals, scoring, how you win and lose, limits, what changes between runs"],
"check_first": ["up to 8 short things Spark should confirm on the screen early, most useful first"],
"watch_out": ["traps, confirmations, things that can't be undone, settings that change the controls"],
"not_covered": ["what the job needs that the documents don't say"]}}"""


def brief(docs: list[Doc], goal: str, address: str, meter: Meter, limit_usd: float = 0.75) -> dict:
    """One Wonder call that reads every document and every picture, and returns the brief."""
    content: list = [{"type": "input_text", "text": BRIEF_RULES.format(address=address, goal=goal)}]
    for d in docs:
        if d.text:
            content.append({"type": "input_text", "text": f"\n\n===== {d.label()} =====\n{d.text}"})
        for pic, caption in zip(d.pictures, d.captions):
            content.append({"type": "input_text", "text": f"\n\nPicture: {caption}"})
            content.append({"type": "input_image", "image_url": image_url(pic, 85)})
    out = Cloud(meter=meter, limit_usd=limit_usd).respond(model=config.TEACHER_MODEL, reasoning={"effort": "medium"}, input=[{"role": "user", "content": content}])
    try:
        raw = extract_json(response_text(out))
    except ValueError:
        raise DocsError("Wonder's notes on the docs couldn't be read, so nothing from them was used") from None
    return clean(raw if isinstance(raw, dict) else {})


def clean(raw: dict) -> dict:
    def strings(v, n):
        return [str(x).strip()[:300] for x in (v if isinstance(v, list) else []) if str(x).strip()][:n]
    controls = []
    for c in raw.get("controls") if isinstance(raw.get("controls"), list) else []:
        if isinstance(c, dict) and str(c.get("input", "")).strip():
            controls.append({"input": str(c["input"]).strip()[:80], "does": str(c.get("does", "")).strip()[:200]})
    return {"app": str(raw.get("app") or "").strip()[:60], "about": str(raw.get("about") or "").strip()[:600], "controls": controls[:40],
            "how_to": strings(raw.get("how_to"), 15), "rules": strings(raw.get("rules"), 15), "check_first": strings(raw.get("check_first"), 8),
            "watch_out": strings(raw.get("watch_out"), 10), "not_covered": strings(raw.get("not_covered"), 8)}


def brief_text(b: dict, read: list[str] | None = None) -> str:
    """The brief as the models see it."""
    if not b:
        return ""
    lines = ["WHAT THE APP'S DOCS SAY" + (f" (read from {', '.join(read)})" if read else "")
             + ". This is unconfirmed: it may describe another version, and the screen wins wherever they disagree."]
    if b.get("about"):
        lines.append(f"About: {b['about']}")
    if b.get("controls"):
        lines.append("Controls:\n" + "\n".join(f"- {c['input']}: {c['does']}" for c in b["controls"]))
    for key, title in (("how_to", "How to do the job, per the docs"), ("rules", "How it behaves"), ("check_first", "Check these on screen first"),
                       ("watch_out", "Watch out for"), ("not_covered", "Not in the docs")):
        if b.get(key):
            lines.append(f"{title}:\n" + "\n".join(f"{i + 1}. {x}" if key in ("how_to", "check_first") else f"- {x}" for i, x in enumerate(b[key])))
    return "\n\n".join(lines)


FOR_SPARK = ("\n\n{brief}\n\nThe user gave these docs so you can save turns: try what they describe before searching for it, and start with the "
             "checks listed. When you finish exploring, say which points you confirmed on screen and which the screen contradicted.")
FOR_WONDER = ("\n\n{brief}\n\nUse the docs for what exploring didn't show, such as keys and shortcuts. Rely only on what the record confirms or "
              "the docs state plainly, and wherever the record and the docs disagree, follow the record.")
