"""The driver, against a real virtual screen."""
import threading

import pytest

from autoharness.desktop import Display, find_tool

pytestmark = pytest.mark.skipif(not find_tool("Xvfb"), reason="needs Xvfb")


def test_screens_started_together_never_collide():
    made = []
    threads = [threading.Thread(target=lambda: made.append(Display(320, 200).start())) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    try:
        assert len({d.number for d in made}) == 4
    finally:
        for d in made:
            d.stop()


def test_keyboard_events_are_the_characters_asked_for():
    from Xlib import X
    from Xlib import display as xd
    d = Display(320, 200).start()
    try:
        conn = xd.Display(f":{d.number}")
        root = conn.screen().root
        win = root.create_window(0, 0, 300, 180, 0, conn.screen().root_depth, event_mask=X.KeyPressMask)
        win.map()
        conn.sync()
        import time
        time.sleep(0.4)
        win.set_input_focus(X.RevertToParent, X.CurrentTime)
        conn.sync()
        time.sleep(0.2)
        text = "Admin123!@#-_/ Az:?"
        d.type(text)
        time.sleep(0.3)
        got = []
        while conn.pending_events():
            e = conn.next_event()
            if e.type == X.KeyPress:
                shift = bool(e.state & X.ShiftMask)
                sym = conn.keycode_to_keysym(e.detail, 1 if shift else 0)
                if sym < 256:  # modifier keys themselves are not characters
                    got.append(chr(sym))
        assert "".join(got) == text
    finally:
        d.stop()
