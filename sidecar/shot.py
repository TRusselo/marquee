#!/usr/bin/env python3
"""marquee-shot: screenshot Marquee's card page and serve it as card.jpg.

Pure logic + stdlib only at import time. Playwright is imported lazily inside
the renderer so `--selftest` runs anywhere with just Python 3.
"""
import os
import sys
import json
import time
import threading
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def cfg():
    """Read all knobs from the environment, with defaults."""
    return {
        "url": os.environ.get("MARQUEE_URL", "http://127.0.0.1:8084").rstrip("/"),
        "width": int(os.environ.get("PANEL_WIDTH", "800")),
        "height": int(os.environ.get("PANEL_HEIGHT", "480")),
        "every": float(os.environ.get("CAPTURE_EVERY", "5")),
        "quality": int(os.environ.get("JPEG_QUALITY", "85")),
        "port": int(os.environ.get("SERVE_PORT", "8088")),
        "settle": float(os.environ.get("SETTLE_SECONDS", "0.8")),
    }


def is_playing(np):
    """True when now-playing.json reports playback."""
    return bool(np.get("playing", False))


def decide(playing, idle_captured):
    """Pure state machine. Returns (action, new_idle_captured).

    action is one of: 'capture' (playing), 'idle' (just stopped, grab one frame),
    'sleep' (idle and already captured).
    """
    if playing:
        return ("capture", False)
    if not idle_captured:
        return ("idle", True)
    return ("sleep", True)


def fetch_json(url, timeout=5):
    """GET url and parse JSON. Raises on network/parse error (caller handles)."""
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


_latest = {"jpg": None}
_latest_lock = threading.Lock()


def publish(jpg):
    """Atomically make jpg the frame served to clients."""
    with _latest_lock:
        _latest["jpg"] = jpg


class CardHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.split("?")[0] != "/card.jpg":
            self.send_error(404, "only /card.jpg")
            return
        with _latest_lock:
            jpg = _latest["jpg"]
        if jpg is None:
            self.send_error(503, "no frame captured yet")
            return
        self.send_response(200)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Content-Length", str(len(jpg)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(jpg)

    def log_message(self, *a):
        pass


def serve(port):
    ThreadingHTTPServer(("", port), CardHandler).serve_forever()


class Renderer:
    """One warm headless-Chromium page held open on the card URL."""

    def __init__(self, url, width, height, quality):
        self.url = f"{url}/image"
        self.width = width
        self.height = height
        self.quality = quality
        self._pw = self._browser = self._page = None

    def start(self):
        from playwright.sync_api import sync_playwright  # lazy: keeps --selftest dep-free
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(
            headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"]
        )
        self._page = self._browser.new_page(
            viewport={"width": self.width, "height": self.height},
            device_scale_factor=1,
        )
        self._page.goto(self.url, wait_until="networkidle", timeout=30000)

    def capture(self):
        return self._page.screenshot(type="jpeg", quality=self.quality)

    def alive(self):
        try:
            return self._page is not None and not self._page.is_closed()
        except Exception:
            return False

    def stop(self):
        try:
            if self._browser:
                self._browser.close()
        except Exception:
            pass
        try:
            if self._pw:
                self._pw.stop()
        except Exception:
            pass


def run():
    c = cfg()
    print(f"marquee-shot: {c['url']}/image -> :{c['port']}/card.jpg "
          f"@ {c['width']}x{c['height']} every {c['every']}s", flush=True)
    threading.Thread(target=serve, args=(c["port"],), daemon=True).start()

    r = Renderer(c["url"], c["width"], c["height"], c["quality"])
    r.start()
    idle_captured = False
    while True:
        try:
            if not r.alive():
                print("renderer died; relaunching", flush=True)
                r.stop()
                r = Renderer(c["url"], c["width"], c["height"], c["quality"])
                r.start()
            playing = is_playing(fetch_json(f"{c['url']}/now-playing.json"))
            action, idle_captured = decide(playing, idle_captured)
            if action == "capture":
                time.sleep(c["settle"])
                publish(r.capture())
            elif action == "idle":
                publish(r.capture())
        except Exception as e:
            print(f"loop error: {e}", flush=True)
        time.sleep(c["every"])


def _selftest():
    assert is_playing({"playing": True}) is True
    assert is_playing({"playing": False}) is False
    assert is_playing({}) is False, "missing key defaults to not playing"

    assert decide(True, False) == ("capture", False)
    assert decide(True, True) == ("capture", False), "playing always resets idle flag"
    assert decide(False, False) == ("idle", True), "first idle tick grabs one frame"
    assert decide(False, True) == ("sleep", True), "subsequent idle ticks do nothing"

    ic = False
    _, ic = decide(True, ic);  assert ic is False
    _, ic = decide(False, ic); assert ic is True
    _, ic = decide(False, ic); assert ic is True
    _, ic = decide(True, ic);  assert ic is False

    # fetch_json round-trips JSON from a local ephemeral server.
    class _H(BaseHTTPRequestHandler):
        def do_GET(self):
            body = b'{"playing": true, "title": "Family Guy"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def log_message(self, *a):
            pass
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    got = fetch_json(f"http://127.0.0.1:{port}/now-playing.json")
    assert is_playing(got) is True and got["title"] == "Family Guy", got
    srv.shutdown()

    # File server: 503 before any frame, image/jpeg 200 after publish().
    _latest["jpg"] = None
    csrv = ThreadingHTTPServer(("127.0.0.1", 0), CardHandler)
    threading.Thread(target=csrv.serve_forever, daemon=True).start()
    cport = csrv.server_address[1]
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{cport}/card.jpg", timeout=5)
        assert False, "expected 503 before first frame"
    except urllib.error.HTTPError as e:
        assert e.code == 503, e.code
    publish(b"\xff\xd8\xff-not-a-real-jpeg-but-bytes")
    with urllib.request.urlopen(f"http://127.0.0.1:{cport}/card.jpg", timeout=5) as r:
        assert r.status == 200
        assert r.headers["Content-Type"] == "image/jpeg", r.headers["Content-Type"]
        assert r.read() == b"\xff\xd8\xff-not-a-real-jpeg-but-bytes"
    csrv.shutdown()
    _latest["jpg"] = None

    print("selftest ok")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
        sys.exit(0)
    c = cfg()
    if "--once" in sys.argv:
        idx = sys.argv.index("--once")
        out = sys.argv[idx + 1] if len(sys.argv) > idx + 1 else "card.jpg"
        r = Renderer(c["url"], c["width"], c["height"], c["quality"])
        r.start()
        time.sleep(c["settle"])
        with open(out, "wb") as f:
            f.write(r.capture())
        r.stop()
        print(f"wrote {out} ({c['width']}x{c['height']})")
        sys.exit(0)
    run()
