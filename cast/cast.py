#!/usr/bin/env python3
"""Marquee — a Plex "now playing" marquee for Google Nest Hubs.
The whole app in one container: front end + back end.

Backend: polls Plex every POLL_SECONDS; while something plays it downloads
poster/backdrop/logo, writes now-playing.json, and casts the card to the Hub;
when idle it releases the Hub.

Frontend (one HTTP server on :8084): serves the card page and art from
output/, the settings UI at /settings, /save, and /release-notes.

Env knobs: PAGE_URL, PLEX_HOST, PLEX_TOKEN, POLL_SECONDS, REPO_DIR,
SERVE_PORT, DATA_DIR. Optional TMDB_API_KEY enables the credits-scene badge;
optional PLEX_USERS / PLEX_DEVICES limit which Plex users and player devices
trigger the marquee (also editable live on the settings page). The cast
device comes from the settings page (auto-discovered via catt scan) or the
HUB_IP env fallback.
"""
import json
import mimetypes
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

VERSION = "1.4.0"
HUB_IP = os.environ.get("HUB_IP", "")
PAGE_URL = os.environ.get("PAGE_URL", "")
PLEX = os.environ.get("PLEX_HOST", "").rstrip("/")
TOKEN = os.environ.get("PLEX_TOKEN", "")
POLL = int(os.environ.get("POLL_SECONDS", "5"))
REPO = os.environ.get("REPO_DIR", "/repo")
TMDB_KEY = os.environ.get("TMDB_API_KEY", "")
SERVE_PORT = int(os.environ.get("SERVE_PORT", "8084"))
def csv_set(value):
    return {v.strip().lower() for v in (value or "").split(",") if v.strip()}


# Comma-separated usernames / device names that may trigger the marquee; empty
# = everyone / any device. MEDIA_* preferred, PLEX_* honored as fallback; env is
# the seed and the settings page adds more.
USERS = csv_set(os.environ.get("MEDIA_USERS", os.environ.get("PLEX_USERS", "")))
DEVICES = csv_set(os.environ.get("MEDIA_DEVICES",
                                 os.environ.get("PLEX_DEVICES", "")))

BACKEND = os.environ.get("MEDIA_BACKEND", "plex").lower()
if BACKEND not in ("plex", "emby"):
    BACKEND = "plex"


def get_session():
    """Current normalized now-playing dict from the configured backend, or None."""
    return emby_current_session() if BACKEND == "emby" else current_session()

OUTPUT = os.path.join(REPO, "output")
JSON_PATH = os.path.join(OUTPUT, "now-playing.json")
DATA_DIR = os.environ.get("DATA_DIR", OUTPUT)
SETTINGS_PATH = os.path.join(DATA_DIR, "settings.json")

THEMES = ("amber", "ice", "crimson", "emerald",
          "campaign", "concrete", "trophy", "bsides")
TEMPLATES = ("spotlight", "split", "hero", "lowerthird", "bigclock", "street")
TITLE_FONTS = ("system", "bebas", "oswald", "playfair", "cinzel", "grotesk")
ACCENT_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
IP_RE = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")
DEFAULT_SETTINGS = {
    "hubIp": "",
    "template": "spotlight",
    "theme": "amber",
    "accent": "",
    "titleFont": "system",
    "posterSide": "right",
    "clockFormat": "12h",
    "clockSeconds": False,
    "showPlot": True, "showGenres": True, "showScores": True,
    "showMediaInfo": True, "showContentRating": True, "showRuntime": True,
    "showProgress": True, "showClock": True,
    "backdrop": True, "logo": True,
    "plexUsers": "", "plexDevices": "",
    "blockLayout": {},
}

EDITABLE_BLOCKS = ("clock", "identity", "meta", "plot", "ratings",
                   "progress", "poster")

_meta_cache = {}  # ratingKey -> extras dict


def plex_url(path):
    return f"{PLEX}{path}{'&' if '?' in path else '?'}X-Plex-Token={TOKEN}"


def fetch_xml(path):
    with urllib.request.urlopen(plex_url(path), timeout=10) as r:
        return ET.fromstring(r.read())


def atomic_write(path, data, mode="w"):
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path))
    with os.fdopen(fd, mode) as f:
        f.write(data)
    os.replace(tmp, path)
    os.chmod(path, 0o644)


def hub_ip():
    """Device picked in settings wins; HUB_IP env is the fallback."""
    return load_settings().get("hubIp") or HUB_IP


def catt(*args):
    result = subprocess.run(["catt", "-d", hub_ip(), *args],
                            capture_output=True, text=True, timeout=90)
    if result.returncode:
        detail = (result.stderr or result.stdout or "unknown catt error").strip()
        raise RuntimeError(f"catt {' '.join(args)} failed: {detail}")
    return result


_scan_cache = {"at": 0.0, "devices": []}


def parse_scan(text):
    """catt scan lines look like: '192.168.1.50 - Living Room - Google Nest Hub'."""
    devices = []
    for line in text.splitlines():
        m = re.match(r"\s*(\d{1,3}(?:\.\d{1,3}){3})\s+-\s+(.+?)\s+-\s+(.*)", line)
        if m:
            devices.append({"ip": m.group(1), "name": m.group(2),
                            "model": m.group(3).strip()})
    return devices


def scan_devices(refresh=False):
    """Google Cast devices announce over mDNS; catt scan collects them."""
    if refresh or time.time() - _scan_cache["at"] > 300:
        try:
            result = subprocess.run(["catt", "scan"], capture_output=True,
                                    text=True, timeout=45)
            _scan_cache.update(at=time.time(),
                               devices=parse_scan(result.stdout))
        except Exception as e:
            print(f"device scan failed: {e}", flush=True)
    return {"devices": _scan_cache["devices"], "current": hub_ip()}


def dashcast_active():
    return "DashCast" in catt("info").stdout


TARGET = os.environ.get("CAST_TARGET", "nest").lower()
if TARGET not in ("nest", "esp32"):
    TARGET = "nest"


def nest_available():
    return bool(hub_ip())


def nest_active():
    return dashcast_active()


def nest_show(page_url):
    sep = "&" if "?" in page_url else "?"
    catt("cast_site", f"{page_url}{sep}cb={int(time.time())}")


def nest_hide():
    catt("stop")


ESP32_HOST = os.environ.get("ESP32_HOST", "")
ESP32_PORT = int(os.environ.get("ESP32_PORT", "80"))


def esp32_endpoint(host, port, path):
    return f"http://{host}:{port}/{path}"


def esp32_json_url(page_url):
    """Derive the now-playing.json URL from PAGE_URL's origin."""
    p = urllib.parse.urlsplit(page_url)
    return f"{p.scheme}://{p.netloc}/now-playing.json"


def esp32_post(path, payload=None):
    data = json.dumps(payload or {}).encode()
    req = urllib.request.Request(
        esp32_endpoint(ESP32_HOST, ESP32_PORT, path), data=data,
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.load(r)


def esp32_available():
    if not ESP32_HOST:
        return False
    try:
        with urllib.request.urlopen(
                esp32_endpoint(ESP32_HOST, ESP32_PORT, "status"), timeout=5) as r:
            json.load(r)
        return True
    except Exception:
        return False


def esp32_active():
    try:
        with urllib.request.urlopen(
                esp32_endpoint(ESP32_HOST, ESP32_PORT, "status"), timeout=5) as r:
            return bool(json.load(r).get("displaying"))
    except Exception:
        return False


def esp32_show(page_url):
    esp32_post("display", {"json_url": esp32_json_url(page_url)})


def esp32_hide():
    esp32_post("stop")


def device_available():
    return esp32_available() if TARGET == "esp32" else nest_available()


def device_active():
    return esp32_active() if TARGET == "esp32" else nest_active()


def device_show(page_url):
    return esp32_show(page_url) if TARGET == "esp32" else nest_show(page_url)


def device_hide():
    return esp32_hide() if TARGET == "esp32" else nest_hide()


_wx_cache = {"at": 0.0, "loc": "", "data": {}}


def weather():
    """Current conditions for the card's Faze mode, via Open-Meteo (free, no
    API key). Location is geolocated once from the server's public IP."""
    if time.time() - _wx_cache["at"] < 900 and _wx_cache["data"]:
        return _wx_cache["data"]
    try:
        if not _wx_cache["loc"]:
            with urllib.request.urlopen(
                    "http://ip-api.com/json/?fields=lat,lon", timeout=10) as r:
                j = json.load(r)
                _wx_cache["loc"] = f"{j['lat']},{j['lon']}"
        lat, lon = _wx_cache["loc"].split(",")
        url = (f"https://api.open-meteo.com/v1/forecast?latitude={lat}"
               f"&longitude={lon}&current=weather_code,is_day,temperature_2m")
        with urllib.request.urlopen(url, timeout=10) as r:
            cur = json.load(r)["current"]
        _wx_cache.update(at=time.time(), data={
            "code": cur["weather_code"], "isDay": cur["is_day"] == 1,
            "temp": cur["temperature_2m"]})
    except Exception as e:
        print(f"weather fetch failed: {e}", flush=True)
        _wx_cache["at"] = time.time()  # don't hammer on failure
    return _wx_cache["data"]


def tmdb_stinger(tmdb_id):
    """['during'|'after', ...] from TMDb keywords (aftercreditsstinger etc.)."""
    url = f"https://api.themoviedb.org/3/movie/{tmdb_id}/keywords?api_key={TMDB_KEY}"
    with urllib.request.urlopen(url, timeout=10) as r:
        names = {k["name"] for k in json.load(r).get("keywords", [])}
    return [w for w, kw in (("during", "duringcreditsstinger"),
                            ("after", "aftercreditsstinger")) if kw in names]


def transcode_to(path, plex_path, w, h):
    inner = urllib.parse.quote(f"{plex_path}?X-Plex-Token={TOKEN}", safe="")
    url = (f"{PLEX}/photo/:/transcode?width={w}&height={h}&minSize=1"
           f"&upscale=1&url={inner}&X-Plex-Token={TOKEN}")
    with urllib.request.urlopen(url, timeout=15) as r:
        atomic_write(os.path.join(OUTPUT, path), r.read(), "wb")


EMBY = os.environ.get("EMBY_HOST", "").rstrip("/")
EMBY_KEY = os.environ.get("EMBY_API_KEY", "")


def emby_url(path):
    base = EMBY + path
    return f"{base}{'&' if '?' in base else '?'}api_key={EMBY_KEY}"


def emby_fetch_json(path):
    with urllib.request.urlopen(emby_url(path), timeout=10) as r:
        return json.load(r)


def emby_image_url(host, key, item_id, kind, w=600, h=900):
    return (f"{host.rstrip('/')}/Items/{item_id}/Images/{kind}"
            f"?maxWidth={w}&maxHeight={h}&api_key={key}")


def emby_save_image(item_id, kind, out_name, w, h):
    url = emby_image_url(EMBY, EMBY_KEY, item_id, kind, w, h)
    with urllib.request.urlopen(url, timeout=15) as r:
        atomic_write(os.path.join(OUTPUT, out_name), r.read(), "wb")


def emby_download_art(item):
    """Save poster/backdrop/logo for an Emby item into output/."""
    out = {"poster": False, "backdrop": False, "logo": False}
    item_id = item.get("Id")
    tags = item.get("ImageTags") or {}
    if item.get("Type") == "Episode" and item.get("SeriesId"):
        poster_id = item["SeriesId"]
    else:
        poster_id = item_id
    try:
        if poster_id:
            emby_save_image(poster_id, "Primary", "poster.jpg", 600, 900)
            out["poster"] = True
    except Exception:
        pass
    backdrop_id = item.get("ParentBackdropItemId") or item.get("SeriesId") or item_id
    try:
        if backdrop_id:
            emby_save_image(backdrop_id, "Backdrop/0", "backdrop.jpg", 1280, 800)
            out["backdrop"] = True
    except Exception:
        pass
    logo_id = item.get("ParentLogoItemId") or item.get("SeriesId") or item_id
    try:
        if "Logo" in tags or logo_id:
            emby_save_image(logo_id, "Logo", "logo.png", 800, 310)
            out["logo"] = True
    except Exception:
        pass
    return out


def download_art(item, rating_key):
    """Save poster.jpg, backdrop.jpg, logo.png into output/."""
    out = {"poster": False, "backdrop": False, "logo": False}
    poster = item.get("grandparentThumb") or item.get("thumb")
    if poster:
        transcode_to("poster.jpg", poster, 600, 900)
        out["poster"] = True
    if item.get("art"):
        transcode_to("backdrop.jpg", item.get("art"), 1280, 800)
        out["backdrop"] = True
    try:
        with urllib.request.urlopen(
                plex_url(f"/library/metadata/{rating_key}/clearLogo"), timeout=15) as r:
            atomic_write(os.path.join(OUTPUT, "logo.png"), r.read(), "wb")
        out["logo"] = True
    except Exception:
        pass
    return out


def library_extras(rating_key, is_movie=False):
    """Genres, IMDb, stinger, art/logo from the full metadata record; cached per item."""
    if rating_key in _meta_cache:
        return _meta_cache[rating_key]
    x = {"genres": [], "imdb": None, "stinger": [],
         "poster": False, "backdrop": False, "logo": False}
    try:
        root = fetch_xml(f"/library/metadata/{rating_key}?includeRatings=1")
        item = root.find("./*")
        if item is not None:
            x["genres"] = [g.get("tag") for g in item.findall("Genre") if g.get("tag")]
            for r in item.findall("Rating"):
                if (r.get("image") or "").startswith("imdb://") and r.get("value"):
                    x["imdb"] = float(r.get("value"))
            if TMDB_KEY and is_movie:
                for g in item.findall("Guid"):
                    if (g.get("id") or "").startswith("tmdb://"):
                        x["stinger"] = tmdb_stinger(g.get("id")[7:])
                        break
            x.update(download_art(item, rating_key))
    except Exception as e:
        print(f"metadata fetch failed for {rating_key}: {e}", flush=True)
    _meta_cache.clear()  # only ever need the current item
    _meta_cache[rating_key] = x
    return x


def pretty_resolution(res):
    if not res:
        return None
    return {"4k": "4K", "sd": "SD"}.get(res.lower(), res + "p" if res.isdigit() else res.upper())


def emby_ticks_to_ms(ticks):
    return int(ticks) // 10000 if ticks is not None else None


def emby_resolution(width, height=None):
    """Label resolution by frame Width. Height is unreliable for
    letterboxed/scope films (a 1080p 2.76:1 movie is 1920x696, which by
    height would mislabel as "696p"). Width tracks the resolution tier."""
    w = int(width) if width else 0
    if w >= 3800:
        return "4K"
    if w >= 2500:
        return "1440p"
    if w >= 1800:
        return "1080p"
    if w >= 1200:
        return "720p"
    if w >= 700:
        return "480p"
    if height:  # width missing/odd -> fall back to height buckets
        return {2160: "4K", 1080: "1080p", 720: "720p", 480: "480p"}.get(
            int(height), f"{int(height)}p")
    return f"{w}px" if w else None


def parse_emby_session(session, extras):
    """One Emby /Sessions entry -> normalized now-playing dict (matches Plex)."""
    item = session.get("NowPlayingItem") or {}
    play = session.get("PlayState") or {}
    is_episode = item.get("Type") == "Episode"
    info = {
        "playing": True,
        "type": (item.get("Type") or "").lower(),
        "key": item.get("Id"),
        "title": item.get("SeriesName") if is_episode else item.get("Name"),
        "year": item.get("ProductionYear"),
    }
    if is_episode and item.get("ParentIndexNumber") and item.get("IndexNumber"):
        info["subtitle"] = (f"S{item['ParentIndexNumber']} · "
                            f"E{item['IndexNumber']} · {item.get('Name')}")
    info["state"] = "paused" if play.get("IsPaused") else "playing"
    offset = emby_ticks_to_ms(play.get("PositionTicks"))
    duration = emby_ticks_to_ms(item.get("RunTimeTicks"))
    if offset is not None and duration:
        info["progress"] = {"offsetMs": offset, "durationMs": duration}
    if duration:
        m = duration // 60000
        info["runtime"] = f"{m // 60}h {m % 60:02d}m" if m >= 60 else f"{m}m"
    if item.get("Overview"):
        info["summary"] = item["Overview"]
    taglines = item.get("Taglines") or []
    if taglines:
        info["tagline"] = taglines[0]
    if item.get("OfficialRating"):
        info["contentRating"] = item["OfficialRating"]
    genres = [g for g in (item.get("Genres") or []) if g]
    if genres:
        info["genres"] = genres[:3]
    streams = item.get("MediaStreams") or []
    video = next((s for s in streams if s.get("Type") == "Video"), None)
    audio = next((s for s in streams if s.get("Type") == "Audio"), None)
    parts = [emby_resolution(video.get("Width"), video.get("Height")) if video else None,
             (video.get("Codec") or "").upper() or None if video else None,
             (audio.get("Codec") or "").upper() or None if audio else None]
    media = " · ".join(p for p in parts if p)
    if media:
        info["media"] = media
    scores = {}
    if item.get("CommunityRating"):
        scores["imdb"] = round(float(item["CommunityRating"]), 1)
    if item.get("CriticRating") is not None:
        scores["rtCritic"] = round(float(item["CriticRating"]))
        scores["rtCriticFresh"] = float(item["CriticRating"]) >= 60
    if scores:
        info["scores"] = scores
    x = extras(item)
    if x.get("stinger"):
        info["stinger"] = x["stinger"]
    info["poster"] = x.get("poster", False)
    info["backdrop"] = x.get("backdrop", False)
    info["logo"] = x.get("logo", False)
    return info


def parse_session(video, extras=library_extras):
    """Video element from /status/sessions -> now-playing dict."""
    a = video.get
    is_episode = a("type") == "episode"
    info = {
        "playing": True,
        "type": a("type"),
        "key": a("ratingKey"),
        "title": a("grandparentTitle") if is_episode else a("title"),
        "year": a("year"),
    }
    if is_episode and a("parentIndex") and a("index"):
        info["subtitle"] = f"S{a('parentIndex')} · E{a('index')} · {a('title')}"

    x = (extras(a("ratingKey"), a("type") == "movie") if a("ratingKey")
         else {"genres": [], "imdb": None, "stinger": [],
               "poster": False, "backdrop": False, "logo": False})

    player = video.find("Player")
    if player is not None and player.get("state"):
        info["state"] = player.get("state")
    if a("viewOffset") and a("duration"):
        info["progress"] = {"offsetMs": int(a("viewOffset")),
                            "durationMs": int(a("duration"))}
    if a("summary"):
        info["summary"] = a("summary")
    if a("tagline"):
        info["tagline"] = a("tagline")
    if x["genres"]:
        info["genres"] = x["genres"][:3]
    if x["stinger"]:
        info["stinger"] = x["stinger"]
    info["poster"] = x["poster"]
    info["backdrop"] = x["backdrop"]
    info["logo"] = x["logo"]
    if a("contentRating"):
        info["contentRating"] = a("contentRating")
    if a("duration"):
        m = int(a("duration")) // 60000
        info["runtime"] = f"{m // 60}h {m % 60:02d}m" if m >= 60 else f"{m}m"
    media = video.find("Media")
    if media is not None:
        parts = [pretty_resolution(media.get("videoResolution")),
                 (media.get("videoCodec") or "").upper() or None,
                 (media.get("audioCodec") or "").upper() or None]
        info["media"] = " · ".join(p for p in parts if p)
    scores = {}
    if "rottentomatoes" in (a("ratingImage") or "") and a("rating"):
        scores["rtCritic"] = round(float(a("rating")) * 10)
        scores["rtCriticFresh"] = "ripe" in a("ratingImage")
    if "rottentomatoes" in (a("audienceRatingImage") or "") and a("audienceRating"):
        scores["rtAudience"] = round(float(a("audienceRating")) * 10)
        scores["rtAudienceFresh"] = "upright" in a("audienceRatingImage")
    if x["imdb"]:
        scores["imdb"] = x["imdb"]
    if scores:
        info["scores"] = scores
    return info


def session_names(video):
    """(user, device) display names for a session; device falls back through
    Player title -> device -> product."""
    user = video.find("User")
    player = video.find("Player")
    u = (user.get("title") or "") if user is not None else ""
    d = ""
    if player is not None:
        d = player.get("title") or player.get("device") or player.get("product") or ""
    return u, d


def session_allowed(video, users=None, devices=None):
    """True when the session's Plex user AND device pass the allow-lists
    (an empty list allows everyone / any device).

    /status/sessions is server-wide: with the owner token it includes every
    shared and home user, so without a filter the marquee reacts to anyone
    streaming from the library.
    """
    users = USERS if users is None else users
    devices = DEVICES if devices is None else devices
    u, d = session_names(video)
    if users and u.lower() not in users:
        return False
    if devices:
        player = video.find("Player")
        if player is None:
            return False
        names = {(player.get(k) or "").lower()
                 for k in ("title", "device", "product")} - {""}
        if not (names & devices):
            return False
    return True


LAST_SESSIONS = []  # every active session from the last poll, filtered or not


def current_session():
    s = load_settings()
    users = USERS | csv_set(s.get("plexUsers"))
    devices = DEVICES | csv_set(s.get("plexDevices"))
    root = fetch_xml("/status/sessions")
    seen, match = [], None
    for video in root.findall("Video"):
        if video.get("type") not in ("movie", "episode"):
            continue
        u, d = session_names(video)
        ok = session_allowed(video, users, devices)
        seen.append({"user": u, "device": d,
                     "title": video.get("title") or "", "allowed": ok})
        if ok and match is None:
            match = parse_session(video)
    LAST_SESSIONS[:] = seen
    return match


def emby_select_session(sessions, users):
    """First session with a Movie/Episode NowPlayingItem for an allowed user."""
    for s in sessions:
        item = s.get("NowPlayingItem")
        if not item or item.get("Type") not in ("Movie", "Episode"):
            continue
        if users and (s.get("UserName") or "").lower() not in users:
            continue
        return s
    return None


_emby_meta_cache = {}    # item Id -> extras dict; current item only (mirrors _meta_cache)
_emby_enrich_cache = {}  # item Id -> enrichment fields; current item only


def emby_extras(item):
    """TMDB stinger + downloaded art for an Emby item; cached once per item.

    Without this, loop() would re-download poster/backdrop/logo and re-hit TMDB
    every POLL_SECONDS for the whole runtime — matching the Plex library_extras
    cache keeps it to one fetch per title.
    """
    key = item.get("Id")
    if key and key in _emby_meta_cache:
        return _emby_meta_cache[key]
    x = {"stinger": [], "poster": False, "backdrop": False, "logo": False}
    try:
        tmdb_id = (item.get("ProviderIds") or {}).get("Tmdb")
        if TMDB_KEY and item.get("Type") == "Movie" and tmdb_id:
            x["stinger"] = tmdb_stinger(tmdb_id)
    except Exception as e:
        print(f"emby stinger failed: {e}", flush=True)
    try:
        x.update(emby_download_art(item))
    except Exception as e:
        print(f"emby art failed: {e}", flush=True)
    if key:
        _emby_meta_cache.clear()  # only ever need the current item
        _emby_meta_cache[key] = x
    return x


def emby_enrich(item):
    """Fill genres/streams/ids from /Items when /Sessions omitted them.

    Emby's NowPlayingItem field population is server/version dependent; some
    servers return a bare item. When the display-critical fields are missing we
    fetch the full record once (cached per title) and merge it in place.
    """
    key = item.get("Id")
    if not key or (item.get("Genres") and item.get("MediaStreams")):
        return
    if key not in _emby_enrich_cache:
        enriched = {}
        try:
            fields = ("Genres,MediaStreams,ProviderIds,Overview,"
                      "OfficialRating,CommunityRating,CriticRating")
            data = emby_fetch_json(f"/Items?Ids={key}&Fields={fields}")
            items = data.get("Items") if isinstance(data, dict) else None
            full = items[0] if items else {}
            for f in ("Genres", "MediaStreams", "ProviderIds", "Overview",
                      "OfficialRating", "CommunityRating", "CriticRating"):
                if not item.get(f) and full.get(f) is not None:
                    enriched[f] = full[f]
        except Exception as e:
            print(f"emby enrich failed: {e}", flush=True)
        _emby_enrich_cache.clear()  # only ever need the current item
        _emby_enrich_cache[key] = enriched
    item.update(_emby_enrich_cache[key])


def emby_current_session():
    sessions = emby_fetch_json("/Sessions")
    s = emby_select_session(sessions, USERS)
    if not s:
        return None
    emby_enrich(s.get("NowPlayingItem") or {})
    return parse_emby_session(s, extras=emby_extras)


def load_settings():
    try:
        with open(SETTINGS_PATH) as f:
            saved = json.load(f)
        return {**DEFAULT_SETTINGS, **{k: v for k, v in saved.items() if k in DEFAULT_SETTINGS}}
    except Exception:
        return dict(DEFAULT_SETTINGS)


def clean_block_layout(value):
    """Keep layout overrides small, numeric, and limited to known card blocks."""
    if not isinstance(value, dict):
        return {}
    cleaned = {}
    for name, position in value.items():
        if name not in EDITABLE_BLOCKS or not isinstance(position, dict):
            continue
        item = {}
        for key, low, high in (("x", -100, 100), ("y", -100, 100),
                               ("width", 5, 100), ("scale", 0.3, 3)):
            number = position.get(key)
            if isinstance(number, (int, float)) and not isinstance(number, bool):
                item[key] = round(max(low, min(high, number)), 2)
        if position.get("align") in ("left", "center", "right"):
            item["align"] = position["align"]
        if item:
            cleaned[name] = item
    return cleaned


class WebHandler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def _send(self, body, ctype="text/html; charset=utf-8", code=200, cors=False):
        data = body if isinstance(body, bytes) else body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        if cors:  # let LAN dashboards / HA fetch the read-only card state
            self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(data)

    def _send_file(self, path, code=200):
        try:
            with open(path, "rb") as f:
                ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
                self._send(f.read(), ctype, code)
        except Exception:
            self._send("not found", "text/plain", 404)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/settings.json":
            self._send(json.dumps(load_settings()), "application/json")
        elif path == "/devices":
            self._send(json.dumps(scan_devices("refresh" in self.path)),
                       "application/json")
        elif path == "/weather":
            self._send(json.dumps(weather()), "application/json")
        elif path == "/sessions":
            self._send(json.dumps({"sessions": LAST_SESSIONS}), "application/json")
        elif path == "/healthz":
            self._send(json.dumps({"ok": True, "version": VERSION}), "application/json")
        elif path == "/api/now-playing.json":
            # Intentional read-only API for ESP32/ESPHome/HA consumers (CORS-enabled).
            try:
                with open(JSON_PATH) as f:
                    body = f.read()
            except Exception:
                body = json.dumps({"playing": False})
            self._send(body, "application/json", cors=True)
        elif path == "/api/healthz":
            self._send(json.dumps({"ok": True, "version": VERSION}),
                       "application/json", cors=True)
        elif path == "/release-notes":
            self._send_file(os.path.join(REPO, "CHANGELOG.md"))
        elif path in ("/", "/settings"):
            self._send_file(os.path.join(REPO, "cast", "settings.html"))
        elif path == "/image":
            self._send_file(os.path.join(OUTPUT, "index.html"))
        else:
            name = os.path.basename(urllib.parse.unquote(path))  # no traversal
            self._send_file(os.path.join(OUTPUT, name))

    def do_POST(self):
        if self.path.split("?")[0] != "/save":
            return self._send("not found", "text/plain", 404)
        try:
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            merged = {**DEFAULT_SETTINGS,
                      **{k: v for k, v in body.items() if k in DEFAULT_SETTINGS}}
            if merged["posterSide"] not in ("left", "right"):
                merged["posterSide"] = "right"
            if merged["theme"] not in THEMES:
                merged["theme"] = "amber"
            if merged["template"] not in TEMPLATES:
                merged["template"] = "spotlight"
            if merged["clockFormat"] not in ("12h", "24h"):
                merged["clockFormat"] = "12h"
            if merged["titleFont"] not in TITLE_FONTS:
                merged["titleFont"] = "system"
            for k in ("plexUsers", "plexDevices"):
                if not isinstance(merged[k], str):
                    merged[k] = ""
            merged["clockSeconds"] = bool(merged["clockSeconds"])
            if not (isinstance(merged["accent"], str)
                    and (merged["accent"] == "" or ACCENT_RE.match(merged["accent"]))):
                merged["accent"] = ""
            if not (isinstance(merged["hubIp"], str)
                    and (merged["hubIp"] == "" or IP_RE.match(merged["hubIp"]))):
                merged["hubIp"] = ""
            merged["blockLayout"] = clean_block_layout(merged["blockLayout"])
            atomic_write(SETTINGS_PATH, json.dumps(merged))
            self._send(json.dumps({"ok": True}), "application/json")
        except Exception as e:
            self._send(json.dumps({"ok": False, "error": str(e)}), "application/json", 400)


def serve_web():
    ThreadingHTTPServer(("", SERVE_PORT), WebHandler).serve_forever()


def loop():
    os.makedirs(DATA_DIR, exist_ok=True)
    if BACKEND == "emby":
        required = (("PAGE_URL", PAGE_URL), ("EMBY_HOST", EMBY),
                    ("EMBY_API_KEY", EMBY_KEY))
    else:
        required = (("PAGE_URL", PAGE_URL), ("PLEX_HOST", PLEX),
                    ("PLEX_TOKEN", TOKEN))
    missing = [name for name, value in required if not value]
    if missing:
        raise SystemExit("Missing required environment variables: " + ", ".join(missing))
    if not os.path.exists(SETTINGS_PATH):
        atomic_write(SETTINGS_PATH, json.dumps(DEFAULT_SETTINGS))
    threading.Thread(target=serve_web, daemon=True).start()
    print(f"Marquee {VERSION} ready on :{SERVE_PORT} (card: /image, settings: /)",
          flush=True)
    # Poll sessions fast (5s) so json/poster/hub flip together on play/stop;
    # talk to the hub only on transitions, plus a slow reconcile pass.
    last_playing, tick = None, 0
    while True:
        try:
            info = get_session()
            atomic_write(JSON_PATH, json.dumps(info or {"playing": False}))
            playing = bool(info)
            if playing != last_playing or tick % 6 == 0:
                if not device_available():
                    if playing and playing != last_playing:
                        print("no display configured — pick a Nest device on the "
                              "settings page, or set HUB_IP / ESP32_HOST", flush=True)
                else:
                    shown = device_active()
                    if playing and not shown:
                        print(f"{BACKEND} playing ({info['title']}) -> showing",
                              flush=True)
                        device_show(PAGE_URL)
                    elif not playing and shown:
                        print(f"{BACKEND} idle -> releasing display", flush=True)
                        device_hide()
            last_playing = playing
            tick += 1
        except Exception as e:
            print(f"loop error: {e}", flush=True)
        time.sleep(POLL)


SAMPLE_SESSION = """<Video type="movie" title="The Devil Wears Prada 2" year="2026"
  summary="Miranda returns." contentRating="PG-13" duration="7141120" ratingKey="79372"
  rating="7.7" ratingImage="rottentomatoes://image.rating.ripe"
  audienceRating="8.4" audienceRatingImage="rottentomatoes://image.rating.upright"
  viewOffset="3600000"
  tagline="She's back, and twice as fierce.">
  <Media videoResolution="1080" videoCodec="h264" audioCodec="eac3"/>
  <Player state="paused"/></Video>"""

SAMPLE_EXTRAS = {"genres": ["Comedy", "Drama"], "imdb": 7.2, "stinger": ["after"],
                 "poster": True, "backdrop": True, "logo": True}

SAMPLE_EMBY_SESSION = {
    "UserName": "Alice",
    "NowPlayingItem": {
        "Name": "The Devil Wears Prada 2", "Type": "Movie",
        "ProductionYear": 2026, "RunTimeTicks": 71411200000,
        "Overview": "Miranda returns.", "OfficialRating": "PG-13",
        "Taglines": ["She's back, and twice as fierce."],
        "Genres": ["Comedy", "Drama"], "Id": "79372",
        "ProviderIds": {"Tmdb": "12345", "Imdb": "tt1234567"},
        "CommunityRating": 7.2, "CriticRating": 77,
        "MediaStreams": [
            {"Type": "Video", "Codec": "h264", "Height": 1080, "Width": 1920},
            {"Type": "Audio", "Codec": "eac3"},
        ],
    },
    "PlayState": {"PositionTicks": 36000000000, "IsPaused": True},
}
SAMPLE_EMBY_EXTRAS = {"stinger": ["after"],
                      "poster": True, "backdrop": True, "logo": True}


def selftest():
    assert BACKEND in ("plex", "emby")
    assert get_session is not None  # dispatcher exists and is chosen by BACKEND
    info = parse_session(ET.fromstring(SAMPLE_SESSION), extras=lambda k, m: SAMPLE_EXTRAS)
    assert info["title"] == "The Devil Wears Prada 2"
    assert info["key"] == "79372"
    assert info["runtime"] == "1h 59m"
    assert info["media"] == "1080p · H264 · EAC3"
    assert info["scores"] == {"rtCritic": 77, "rtCriticFresh": True,
                              "rtAudience": 84, "rtAudienceFresh": True, "imdb": 7.2}
    assert info["genres"] == ["Comedy", "Drama"]
    assert info["tagline"] == "She's back, and twice as fierce."
    assert info["progress"] == {"offsetMs": 3600000, "durationMs": 7141120}
    assert info["state"] == "paused"
    assert info["stinger"] == ["after"]
    assert info["poster"] and info["backdrop"] and info["logo"]
    ep = ET.fromstring(SAMPLE_SESSION)
    ep.set("type", "episode")
    ep.set("grandparentTitle", "Severance")
    ep.set("parentIndex", "2")
    ep.set("index", "5")
    info = parse_session(ep, extras=lambda k, m: dict(SAMPLE_EXTRAS, stinger=[]))
    assert info["title"] == "Severance"
    assert info["subtitle"] == "S2 · E5 · The Devil Wears Prada 2"
    merged = {**DEFAULT_SETTINGS, **{"posterSide": "left", "bogus": 1, "showPlot": False}}
    assert "bogus" not in DEFAULT_SETTINGS and merged["posterSide"] == "left" \
        and merged["showPlot"] is False and merged["showClock"] is True \
        and merged["template"] == "spotlight"
    layout = clean_block_layout({"identity": {"x": 12.345, "y": -200, "width": 140,
                                              "scale": 9, "height": 50,
                                              "align": "center"},
                                 "plot": {"align": "diagonal"},
                                 "unknown": {"x": 1}})
    assert layout == {"identity": {"x": 12.35, "y": -100, "width": 100,
                                   "scale": 3, "align": "center"}}
    assert ACCENT_RE.match("#A1b2C3") and not ACCENT_RE.match("red") \
        and not ACCENT_RE.match("#12345")
    v = ET.fromstring(SAMPLE_SESSION)
    assert session_allowed(v, set(), set()) and not session_allowed(v, {"alice"}, set())
    v.append(ET.Element("User", {"id": "1", "title": "Alice"}))
    assert session_allowed(v, {"alice"}, set()) and not session_allowed(v, {"bob"}, set())
    assert not session_allowed(v, set(), {"office phone"})  # Player has no names yet
    player = v.find("Player")
    player.set("title", "Office Phone")
    player.set("device", "Pixel 9")
    player.set("product", "Plex for Android")
    assert session_allowed(v, {"alice"}, {"office phone"})
    assert session_allowed(v, set(), {"pixel 9"})
    assert not session_allowed(v, {"alice"}, {"living room tv"})
    assert csv_set(" Alice, ,Office Phone ") == {"alice", "office phone"}
    scan = parse_scan("Scanning Chromecasts...\n"
                      "192.168.1.50 - Living Room - Google Inc. Google Nest Hub\n"
                      "not a device line")
    assert scan == [{"ip": "192.168.1.50", "name": "Living Room",
                     "model": "Google Inc. Google Nest Hub"}]
    assert IP_RE.match("10.0.0.2") and not IP_RE.match("nest.local")
    einfo = parse_emby_session(SAMPLE_EMBY_SESSION, extras=lambda item: SAMPLE_EMBY_EXTRAS)
    assert einfo["type"] == "movie"
    assert einfo["title"] == "The Devil Wears Prada 2"
    assert einfo["year"] == 2026
    assert einfo["state"] == "paused"
    assert einfo["runtime"] == "1h 59m"
    assert einfo["media"] == "1080p · H264 · EAC3"
    assert einfo["progress"] == {"offsetMs": 3600000, "durationMs": 7141120}
    assert einfo["genres"] == ["Comedy", "Drama"]
    assert einfo["scores"] == {"imdb": 7.2, "rtCritic": 77, "rtCriticFresh": True}
    assert einfo["stinger"] == ["after"]
    assert einfo["poster"] and einfo["backdrop"] and einfo["logo"]
    assert einfo["tagline"] == "She's back, and twice as fierce."
    # episode shape
    eep = json.loads(json.dumps(SAMPLE_EMBY_SESSION))
    eep["NowPlayingItem"].update(Type="Episode", SeriesName="Severance",
                                 ParentIndexNumber=2, IndexNumber=5, Name="The Rundown")
    einfo = parse_emby_session(eep, extras=lambda item: dict(SAMPLE_EMBY_EXTRAS, stinger=[]))
    assert einfo["title"] == "Severance"
    assert einfo["subtitle"] == "S2 · E5 · The Rundown"
    # resolution is labeled by Width, not Height (scope/letterboxed films)
    assert emby_resolution(1920, 1080) == "1080p"
    assert emby_resolution(1920, 696) == "1080p"   # 2.76:1 scope film
    assert emby_resolution(3840, 1600) == "4K"     # 2.40:1 UHD
    assert emby_resolution(1280, 720) == "720p"
    assert emby_resolution(None, 1080) == "1080p"  # width missing -> height fallback
    assert emby_resolution(None, None) is None
    scope = json.loads(json.dumps(SAMPLE_EMBY_SESSION))
    scope["NowPlayingItem"]["MediaStreams"] = [
        {"Type": "Video", "Codec": "h264", "Height": 696, "Width": 1920},
        {"Type": "Audio", "Codec": "aac"}]
    sinfo = parse_emby_session(scope, extras=lambda item: SAMPLE_EMBY_EXTRAS)
    assert sinfo["media"] == "1080p · H264 · AAC"
    assert emby_image_url("http://emby:8096", "KEY", "79372", "Primary") == (
        "http://emby:8096/Items/79372/Images/Primary"
        "?maxWidth=600&maxHeight=900&api_key=KEY")
    assert emby_image_url("http://emby:8096/", "KEY", "79372", "Backdrop/0",
                          600, 400) == (
        "http://emby:8096/Items/79372/Images/Backdrop/0"
        "?maxWidth=600&maxHeight=400&api_key=KEY")
    sessions = [
        {"UserName": "Bob"},  # no NowPlayingItem -> skipped
        {"UserName": "Alice", "NowPlayingItem": {"Type": "Photo"}},  # wrong type
        {"UserName": "Alice", "NowPlayingItem": {"Type": "Movie", "Id": "9"},
         "PlayState": {}},
    ]
    assert emby_select_session(sessions, set()) is sessions[2]
    assert emby_select_session(sessions, {"alice"}) is sessions[2]
    assert emby_select_session(sessions, {"bob"}) is None
    assert TARGET in ("nest", "esp32")
    # Nest device functions exist and are the chosen dispatch
    assert device_available is not None and device_show is not None
    assert device_hide is not None and device_active is not None
    assert esp32_endpoint("10.0.0.5", 80, "display") == "http://10.0.0.5:80/display"
    assert esp32_endpoint("10.0.0.5", 8080, "stop") == "http://10.0.0.5:8080/stop"
    # The card's JSON url derived from PAGE_URL's origin
    assert esp32_json_url("http://192.168.1.10:8084/image") == \
        "http://192.168.1.10:8084/now-playing.json"
    print("selftest ok")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    else:
        loop()
