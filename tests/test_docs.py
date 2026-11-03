"""Docs a person hands over before teaching: read into text and pictures here, then one Wonder call turns them into a brief
for Spark. No network or model is needed: the cloud is faked, and web pages come from a tiny local server."""
import io
import json
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np
import pytest
from PIL import Image

from autoharness import docs, uiteam


def tiny_pdf(lines: list[str], picture_page: bool = False) -> bytes:
    """A real PDF with one page of text, and optionally a second page with no text, like a diagram."""
    text = "BT /F1 12 Tf 72 720 Td 14 TL " + " ".join(f"({x}) '" for x in lines) + " ET"
    pages = [text] + (["0 0 1 rg 100 100 400 400 re f"] if picture_page else [])
    objs = ["<< /Type /Catalog /Pages 2 0 R >>",
            f"<< /Type /Pages /Kids [{' '.join(f'{4 + 2 * i} 0 R' for i in range(len(pages)))}] /Count {len(pages)} >>",
            "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    for i, content in enumerate(pages):
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {5 + 2 * i} 0 R /Resources << /Font << /F1 3 0 R >> >> >>")
        objs.append(f"<< /Length {len(content)} >>\nstream\n{content}\nendstream")
    out, offsets = b"%PDF-1.4\n", []
    for n, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{n} 0 obj\n{body}\nendobj\n".encode()
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode() + b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return out


def png(color=(200, 30, 30), size=(64, 40)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


def docx(paragraphs: list[str]) -> bytes:
    body = "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paragraphs)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", f'<w:document xmlns:w="x"><w:body>{body}</w:body></w:document>')
    return buf.getvalue()


PAGE = """<!doctype html><html><head><title>Robots: keys</title><style>p{color:red}</style><script>var hidden = "not docs";</script></head>
<body><nav>Home | Other games</nav><h1>Playing</h1><p>Move with the keys below. Press <kbd>T</kbd> to teleport.</p>
<table><tr><th>Key</th><th>Does</th></tr><tr><td>Y</td><td>up and left</td></tr></table>
<ul><li>Robots move toward you.</li><li>Two robots that collide leave a heap.</li></ul><img src="k.png" alt="the keypad layout"></body></html>"""


def test_every_kind_of_doc_is_read(tmp_path):
    (tmp_path / "manual.pdf").write_bytes(tiny_pdf(["Press T to teleport.", "Press W to wait for the robots."], picture_page=True))
    (tmp_path / "keys.png").write_bytes(png())
    (tmp_path / "keys.html").write_text(PAGE)
    (tmp_path / "notes.md").write_text("# Notes\n\nThe   board   is 45 x 30.\n\n\n\nLevel 1 has 10 robots.")
    (tmp_path / "guide.docx").write_bytes(docx(["Safe teleports are limited.", "Score 10 per robot."]))
    (tmp_path / ".hidden.txt").write_text("not this")
    read = {d.name: d for d in docs.read([str(tmp_path)])}
    assert sorted(read) == ["guide.docx", "keys.html", "keys.png", "manual.pdf", "notes.md"]
    pdf = read["manual.pdf"]
    assert pdf.kind == "PDF" and pdf.detail == "2 pages"
    assert "Press T to teleport." in pdf.text and "[page 1]" in pdf.text
    assert len(pdf.pictures) == 1 and pdf.captions == ["manual.pdf, page 2"]  # the page with no words is read as a picture
    assert read["keys.png"].kind == "picture" and read["keys.png"].pictures[0].shape == (40, 64, 3)
    page = read["keys.html"]
    assert page.kind == "web page" and page.detail == "Robots: keys"
    assert "Press T to teleport." in page.text and "| Y | up and left" in page.text and "- Robots move toward you." in page.text
    assert "[picture: the keypad layout]" in page.text
    assert "not docs" not in page.text and "Other games" not in page.text and "color:red" not in page.text
    assert "The board is 45 x 30.\n\nLevel 1" in read["notes.md"].text
    assert read["guide.docx"].text == "Safe teleports are limited.\nScore 10 per robot."


def test_anything_unreadable_is_an_error_up_front(tmp_path):
    with pytest.raises(docs.DocsError, match="can't find"):
        docs.read([str(tmp_path / "nope.pdf")])
    (tmp_path / "game.exe").write_bytes(b"MZ\x00\x00" * 100)
    with pytest.raises(docs.DocsError, match="PDFs, pictures, web pages"):
        docs.read([str(tmp_path / "game.exe")])
    (tmp_path / "broken.pdf").write_bytes(b"%PDF-1.4 not really")
    with pytest.raises(docs.DocsError, match="isn't a PDF"):
        docs.read([str(tmp_path / "broken.pdf")])
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(docs.DocsError, match="has no PDFs"):
        docs.read([str(empty)])


def test_uploads_keep_the_name_people_gave(tmp_path):
    f = tmp_path / "0123456789ab-Manual.txt"
    f.write_text("Hi")
    assert docs.read([str(f)])[0].name == "Manual.txt"


class Site(BaseHTTPRequestHandler):
    def do_GET(self):
        body, kind = {"/help/keys": (PAGE.encode(), "text/html; charset=utf-8"), "/manual": (tiny_pdf(["Arrow keys slide the tiles."]), "application/pdf"),
                      "/controls": (png(), "image/png")}.get(self.path, (b"", ""))
        self.send_response(200 if body else 404)
        self.send_header("Content-Type", kind or "text/plain")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


def test_web_addresses_are_read_by_what_they_send():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Site)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        page, pdf, pic = docs.read([f"{base}/help/keys", f"{base}/manual", f"{base}/controls"])
        assert page.kind == "web page" and "Press T to teleport." in page.text and page.name == f"127.0.0.1:{server.server_port}/help/keys"
        assert pdf.kind == "PDF" and "Arrow keys slide the tiles." in pdf.text  # no .pdf in the address: the content says so
        assert pic.kind == "picture"
        with pytest.raises(docs.DocsError, match="couldn't open"):
            docs.read([f"{base}/missing"])
    finally:
        server.shutdown()


def test_long_docs_are_trimmed_and_say_so():
    short, long_ = docs.Doc("keys.txt", "text", text="k" * 100), docs.Doc("manual.pdf", "PDF", text="m" * 5000)
    pics = docs.Doc("shots", "picture", pictures=[np.zeros((2, 2, 3), np.uint8)] * 3, captions=["a", "b", "c"])
    pages = docs.Doc("scan.pdf", "PDF", pictures=[np.zeros((2, 2, 3), np.uint8)] * 3, captions=["1", "2", "3"])
    cut = docs.fit([long_, short, pages, pics], max_chars=1100, max_pictures=4)
    assert short.text == "k" * 100 and len(long_.text) == 1000  # the short one is kept whole
    assert len(pics.pictures) == 3 and len(pages.pictures) == 1  # pictures people chose come before scanned pages
    assert cut == ["only the first 1,000 of 5,000 characters of manual.pdf", "2 of the pictures in scan.pdf"]
    assert docs.fit([docs.Doc("a", "text", text="fine")]) == []


REPLY = {"app": "Robots", "about": "Turn-based: you move one square, then every robot steps toward you.",
         "controls": [{"input": "Y K U H L B J N", "does": "move one square"}, {"input": "T", "does": "teleport to a safe square"}, {"bad": 1}],
         "how_to": ["Start a new game with Ctrl+N", "Move away from robots until they collide"], "rules": ["Two robots that collide become a heap"],
         "check_first": ["Does pressing L move right?", "Does T teleport?"], "watch_out": ["Random teleport can land next to a robot"],
         "not_covered": ["How the screen shows a cleared level"], "extra": "ignored"}


def test_wonder_reads_everything_once_and_writes_a_brief_for_spark(monkeypatch):
    sent = {}

    def respond(self, **body):
        sent.update(body)
        return {"output": [{"type": "message", "content": [{"type": "output_text", "text": "```json\n" + json.dumps(REPLY) + "\n```"}]}]}
    monkeypatch.setattr(docs.Cloud, "respond", respond)
    read = [docs.Doc("manual.pdf", "PDF", text="Press T to teleport.", detail="2 pages"), docs.Doc("keys.png", "picture", pictures=[np.zeros((4, 4, 3), np.uint8)], captions=["keys.png"])]
    b = docs.brief(read, "Clear level 1", "vnc://gamepc:5900", uiteam.Meter())
    assert sent["model"] == docs.config.TEACHER_MODEL
    content = sent["input"][0]["content"]
    assert "Job: Clear level 1" in content[0]["text"] and "===== manual.pdf (PDF, 2 pages) =====\nPress T to teleport." in content[1]["text"]
    assert [c["type"] for c in content].count("input_image") == 1
    assert b["controls"] == REPLY["controls"][:2] and "extra" not in b  # a model's reply is checked like any outside input
    text = docs.brief_text(b, ["manual.pdf", "keys.png"])
    assert text.startswith("WHAT THE APP'S DOCS SAY (read from manual.pdf, keys.png). This is unconfirmed")
    assert "- T: teleport to a safe square" in text and "Check these on screen first:\n1. Does pressing L move right?" in text
    assert "screen wins" in docs.FOR_WONDER.format(brief="x") or "follow the record" in docs.FOR_WONDER.format(brief="x")


def test_a_brief_that_isnt_json_is_an_error_not_a_guess(monkeypatch):
    monkeypatch.setattr(docs.Cloud, "respond", lambda self, **b: {"output": [{"type": "message", "content": [{"type": "output_text", "text": "Sorry, I can't."}]}]})
    with pytest.raises(docs.DocsError, match="nothing from them was used"):
        docs.brief([docs.Doc("a.txt", "text", text="x")], "job", "app", uiteam.Meter())


def test_the_docs_help_pick_the_way(monkeypatch):
    sent = {}

    def respond(self, **body):
        sent.update(body)
        return {"output": [{"type": "message", "content": [{"type": "output_text", "text": '{"way": "program", "why": "Each move depends on the robots.", "job": "clear_level", "app": "Robots"}'}]}]}
    monkeypatch.setattr(uiteam.Cloud, "respond", respond)
    chosen = uiteam.choose_way("vnc://gamepc:5900", "Clear level 1", uiteam.Meter(), docs=REPLY)
    assert chosen["way"] == "program"
    assert "What the app's docs say about it: Turn-based" in sent["input"][0]["content"][0]["text"]


def test_only_uploaded_files_or_web_addresses_can_be_docs(tmp_path):
    from autoharness import server
    secret = tmp_path / "id_rsa"
    secret.write_text("private")
    with pytest.raises(ValueError, match="wasn't uploaded"):
        server.start_ui_teach("vnc://127.0.0.1:1", "Win", {}, docs=[str(secret)])


def test_teaching_with_docs_reads_them_before_any_spending_and_hands_the_brief_on(tmp_path, monkeypatch):
    """The whole door, with the screen and the models faked: docs are read, Wonder's brief goes to the way chooser and to
    the lesson, and the total a person sees includes the reading."""
    import time
    from autoharness import server, targets

    class Screen:
        def stop(self):
            pass

        def shot(self):
            return np.zeros((4, 4, 3), np.uint8)

    class Tgt:
        def __init__(self, spec, display):
            self.spec = spec

        def describe(self):
            return "a desktop app"

        def stop(self):
            pass
    got = {}

    def brief(read, goal, address, meter, limit_usd):
        got["read"] = [d.name for d in read]
        meter.usd += 0.07
        return docs.clean(REPLY)

    def choose(address, goal, meter, docs=None):
        got["chose_with"] = docs
        return {"way": "program", "why": "It's a game.", "job": "clear_level", "app": "Robots"}

    def teach_program(spec, goal, inputs, display, target, emit, stop, chosen, **kw):
        got.update(kw)
        emit({"type": "learned", "id": "robots", "usd": 1.0})
        return {"ok": True}
    monkeypatch.setattr(server, "UPLOADS", tmp_path)
    monkeypatch.setattr(server.guides, "find", lambda spec, names: [])  # no network in tests
    monkeypatch.setattr(server, "_keep_last_frame", lambda job, display: None)
    monkeypatch.setattr(targets, "open_screen", lambda spec: Screen())
    monkeypatch.setattr(targets, "Target", Tgt)
    monkeypatch.setattr(docs, "brief", brief)
    monkeypatch.setattr(uiteam, "choose_way", choose)
    monkeypatch.setattr(uiteam, "teach_program", teach_program)
    manual = tmp_path / "0123456789ab-keys.txt"
    manual.write_text("Press T to teleport.")
    job = server.start_ui_teach("some-game", "Clear level 1", {}, docs=[str(manual)], limit=3)
    for _ in range(100):
        if job.status != "running":
            break
        time.sleep(0.02)
    kinds = [e["type"] for e in job.events]
    assert kinds[:3] == ["docs", "brief", "way"], kinds
    assert job.events[0]["read"] == ["keys.txt (text)"] and got["read"] == ["keys.txt"]
    assert got["chose_with"]["controls"][1]["input"] == "T"
    assert got["docs"].startswith("WHAT THE APP'S DOCS SAY (read from keys.txt)") and "- T: teleport to a safe square" in got["docs"]
    assert got["limit_usd"] == pytest.approx(3 - 0.07)  # the lesson's limit is what's left after reading
    (learned,) = [e for e in job.events if e["type"] == "learned"]
    assert learned["usd"] == pytest.approx(1.07)


def test_a_doc_that_cant_be_read_stops_the_lesson_before_any_spending(tmp_path, monkeypatch):
    import time
    from autoharness import server, targets
    monkeypatch.setattr(server, "UPLOADS", tmp_path)
    monkeypatch.setattr(server.guides, "find", lambda spec, names: [])
    monkeypatch.setattr(targets, "open_screen", lambda spec: type("S", (), {"stop": lambda self: None})())
    monkeypatch.setattr(targets, "Target", lambda spec, d: type("T", (), {"describe": lambda self: "x", "stop": lambda self: None})())
    monkeypatch.setattr(uiteam.Cloud, "respond", lambda self, **b: pytest.fail("nothing may be spent"))
    bad = tmp_path / "0123456789ab-game.exe"
    bad.write_bytes(b"MZ\x00" * 50)
    job = server.start_ui_teach("some-game", "Win", {}, docs=[str(bad)])
    for _ in range(100):
        if job.status != "running":
            break
        time.sleep(0.02)
    assert job.status == "failed"
    assert job.events[0] == {**job.events[0], "type": "error", "text": f"The docs: can't read game.exe: it reads {docs.WHAT_IT_READS}."}
