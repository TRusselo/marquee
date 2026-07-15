#!/usr/bin/env python3
"""Marquee — a "now playing" marquee for Google Cast displays and ESP32 panels.
The whole app in one container: front end + back end.

Backend: polls the media server every POLL_SECONDS; while something plays it
downloads poster/backdrop/logo/cast headshots, writes now-playing.json, and
shows the card on the display; when idle it releases the display.

Two seams, each chosen by env and each defaulting to the original behavior:
  MEDIA_BACKEND=plex|emby|jellyfin -> get_session() -> current_session() / emby_current_session()
                            (jellyfin shares the emby path — API-compatible fork)
  CAST_TARGET=nest|esp32    -> device_show()  -> catt cast_site / HTTP POST

Frontend (one HTTP server on :8084): serves the card page and art from
output/, the settings UI at /settings, /save, /release-notes, and a read-only
CORS API at /api/now-playing.json, /api/settings and /api/healthz.

Settings live in two profiles (cast, esp); each display fetches its own with
?profile=<name> on /settings.json or /api/settings, and POSTs it back to
/save?profile=<name>. Omitting the name means the default profile, so a client
that knows nothing about profiles still works. Globals (hubIp, the session
filters, weatherZip) are shared; everything else is per-profile.

Env knobs: PAGE_URL, POLL_SECONDS, REPO_DIR, SERVE_PORT, DATA_DIR.
  Plex:  PLEX_HOST, PLEX_TOKEN
  Emby:  EMBY_HOST, EMBY_API_KEY
  Jellyfin: JELLYFIN_HOST, JELLYFIN_API_KEY (or the EMBY_ pair; shared backend)
  Nest:  HUB_IP (or type/pick a device on the settings page; catt scan is mDNS,
         which many networks drop -- the field takes a plain IP)
  ESP32: ESP32_HOST, ESP32_PORT
Optional TMDB_API_KEY enables the credits-scene badge. Optional MEDIA_USERS /
MEDIA_DEVICES (PLEX_USERS / PLEX_DEVICES honored as fallbacks) limit which
users and player devices trigger the marquee; both backends honor both filters.

HUB_IP, MEDIA_USERS and MEDIA_DEVICES are container-level *defaults*: a value
typed into the corresponding settings-page field replaces them, and an empty
field inherits them. /env-defaults serves those three -- and only those three,
by allowlist -- so the page can show them as placeholders. A filter nobody can
see is a filter that lies.
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

VERSION = "1.6.0"
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
# = everyone / any device. MEDIA_* preferred, PLEX_* honored as fallback. The
# env var is the container-level default: whatever is typed on the settings page
# replaces it, exactly as HUB_IP behaves. The raw strings are kept so the
# settings page can show them as placeholders -- an env filter nobody can see is
# an env filter that lies.
ENV_USERS = os.environ.get("MEDIA_USERS", os.environ.get("PLEX_USERS", ""))
ENV_DEVICES = os.environ.get("MEDIA_DEVICES", os.environ.get("PLEX_DEVICES", ""))
USERS = csv_set(ENV_USERS)
DEVICES = csv_set(ENV_DEVICES)


def filter_set(saved, env_default):
    """The allow-list actually in force: what the settings page says, or the
    container's env default when that field is blank.

    Overrides rather than merges. A union would let an env var filter sessions
    that the settings page shows no sign of, and could never be lifted from the
    UI -- clearing the field would change nothing.
    """
    chosen = csv_set(saved)
    return chosen if chosen else csv_set(env_default)


# Only these env vars are ever shown to the settings page. An allowlist, not a
# denylist: a future PLEX_TOKEN-shaped variable must not leak by default.
ENV_HINT_KEYS = ("hubIp", "plexUsers", "plexDevices")


def env_defaults():
    """Container-level defaults the settings page shows as placeholders, so a
    blank field reads as "inheriting this" instead of "nothing is set"."""
    return {"hubIp": HUB_IP, "plexUsers": ENV_USERS, "plexDevices": ENV_DEVICES}

BACKEND = os.environ.get("MEDIA_BACKEND", "plex").lower()
if BACKEND not in ("plex", "emby", "jellyfin"):
    BACKEND = "plex"


def uses_emby_backend(backend):
    """Jellyfin forked from Emby; the /Sessions, /Items and image APIs this app
    uses are identical (verified against Jellyfin 10.11), so both share the Emby
    session path and the same env-var seam."""
    return backend in ("emby", "jellyfin")


EMBY_FAMILY = uses_emby_backend(BACKEND)


def get_session():
    """Current normalized now-playing dict from the configured backend, or None."""
    return emby_current_session() if EMBY_FAMILY else current_session()

OUTPUT = os.path.join(REPO, "output")
JSON_PATH = os.path.join(OUTPUT, "now-playing.json")
DATA_DIR = os.environ.get("DATA_DIR", OUTPUT)
SETTINGS_PATH = os.path.join(DATA_DIR, "settings.json")

THEMES = ("amber", "ice", "crimson", "emerald",
          "campaign", "concrete", "trophy", "bsides")
TEMPLATES = ("spotlight", "split", "hero", "lowerthird", "bigclock", "street",
             "onesheet")
TITLE_FONTS = ("system", "bebas", "oswald", "playfair", "cinzel", "grotesk")
ACCENT_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
IP_RE = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")
# The flat settings shape the card and settings pages consume. Settings are
# stored per-profile now (see PROFILE_BASE / migrate_settings), but this stays
# the canonical list of every key a page may read, and selftest asserts each
# one still has a home.
DEFAULT_SETTINGS = {
    "hubIp": "",
    "template": "spotlight",
    "theme": "amber",
    "accent": "",
    "titleFont": "system",
    "bodyFont": "system",
    "posterSide": "right",
    "clockFormat": "12h",
    "clockSeconds": False,
    "showPlot": True, "showGenres": True, "showScores": True,
    "showMediaInfo": True, "showContentRating": True, "showRuntime": True,
    "showProgress": True, "showClock": True,
    "backdrop": True, "logo": True,
    "plexUsers": "", "plexDevices": "",
    "rotateSeconds": 30,
    "showWeather": False, "weatherZip": "", "weatherUnits": "f",
    "blockLayout": {},
}

EDITABLE_BLOCKS = ("clock", "identity", "meta", "plot", "ratings",
                   "progress", "poster", "stinger",
                   "tagline", "badges", "tracks", "cast")

CAST_MAX = 6            # top-billed actors shown on the card
HEADSHOT_PX = (150, 150)

PROFILES = ("cast", "esp")            # one Cast/Nest display, one ESP panel
GLOBAL_KEYS = ("default", "hubIp", "plexUsers", "plexDevices", "weatherZip",
               "rotateSeconds")
# Globals are not all strings, so migrating and saving them needs the type.
GLOBAL_DEFAULTS = {"hubIp": "", "plexUsers": "", "plexDevices": "",
                   "weatherZip": "", "rotateSeconds": 30}


def coerce_global(key, value):
    """One global setting, validated to its own type."""
    if key == "rotateSeconds":
        return clamp_rotate(value)
    return value if isinstance(value, str) else GLOBAL_DEFAULTS[key]
DENSITIES = ("full", "compact", "minimal", "custom")
ORIENTATIONS = ("auto", "landscape", "portrait")

# Elements a density preset controls. Poster/title/year/contentRating/progress
# are always on, so they are not listed here.
DENSITY_PRESETS = {
    "full": {"showPlot": True, "showGenres": True, "showScores": True,
             "showMediaInfo": True, "showRuntime": True, "showClock": True,
             "showTagline": True, "showBadges": True, "showPlayMethod": True,
             "showTracks": True, "showCast": True, "showChapters": True},
    "compact": {"showPlot": True, "showGenres": True, "showScores": True,
                "showMediaInfo": True, "showRuntime": True, "showClock": True,
                "showTagline": False, "showBadges": False, "showPlayMethod": True,
                "showTracks": False, "showCast": False, "showChapters": False},
    "minimal": {"showPlot": False, "showGenres": False, "showScores": False,
                "showMediaInfo": False, "showRuntime": False, "showClock": False,
                "showTagline": False, "showBadges": False, "showPlayMethod": False,
                "showTracks": False, "showCast": False, "showChapters": False},
}

# Appearance keys that live inside a profile (everything not in GLOBAL_KEYS).
PROFILE_BASE = {
    "template": "spotlight",
    "theme": "amber",
    "accent": "",
    "titleFont": "system",
    "bodyFont": "system",
    "posterSide": "right",
    "clockFormat": "12h",
    "clockSeconds": False,
    "showContentRating": True, "showProgress": True,
    "backdrop": True, "logo": True,
    "showWeather": False, "weatherUnits": "f",
    "blockLayout": {},
    "density": "full",
    "orientation": "auto",
}


def profile_defaults(density="full", **overrides):
    """A complete profile: always-on elements + the density preset + overrides."""
    p = dict(PROFILE_BASE)
    p.update(DENSITY_PRESETS.get(density, DENSITY_PRESETS["full"]))
    p["density"] = density if density in DENSITIES else "full"
    p.update(overrides)
    return p

_meta_cache = {}  # ratingKey -> extras dict


def plex_url(path):
    return f"{PLEX}{path}{'&' if '?' in path else '?'}X-Plex-Token={TOKEN}"


def fetch_xml(path):
    with urllib.request.urlopen(plex_url(path), timeout=10) as r:
        return ET.fromstring(r.read())


def atomic_write(path, data, mode="w"):
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=parent or None)
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


def profile_url(page_url, profile):
    """Tag a card URL with the profile whose settings it should render."""
    if query_profile(page_url):
        return page_url
    sep = "&" if "?" in page_url else "?"
    return f"{page_url}{sep}profile={profile}"


def nest_available():
    return bool(hub_ip())


def nest_active():
    return dashcast_active()


def nest_show(page_url):
    # profile_url always leaves a "?" behind, so "&cb=" is safe to append.
    url = profile_url(page_url, "cast")
    catt("cast_site", f"{url}&cb={int(time.time())}")


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


_wx_cache = {"at": 0.0, "zip": None, "loc": "", "data": {}}


def weather():
    """Current conditions via Open-Meteo (free, no API key). Location comes
    from the ZIP in settings (zippopotam.us geocode) or, when blank, from the
    server's public IP. Refreshes every 15 minutes."""
    zip_code = re.sub(r"[^0-9]", "", load_settings().get("weatherZip") or "")[:5]
    fresh = time.time() - _wx_cache["at"] < 900
    if fresh and _wx_cache["zip"] == zip_code and _wx_cache["data"]:
        return _wx_cache["data"]
    try:
        if _wx_cache["zip"] != zip_code or not _wx_cache["loc"]:
            if zip_code:
                with urllib.request.urlopen(
                        f"https://api.zippopotam.us/us/{zip_code}", timeout=10) as r:
                    p = json.load(r)["places"][0]
                    _wx_cache["loc"] = f"{p['latitude']},{p['longitude']}"
            else:
                with urllib.request.urlopen(
                        "http://ip-api.com/json/?fields=lat,lon", timeout=10) as r:
                    j = json.load(r)
                    _wx_cache["loc"] = f"{j['lat']},{j['lon']}"
            _wx_cache["zip"] = zip_code
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


# Jellyfin honors the same api_key query auth and endpoint shapes as Emby, so
# JELLYFIN_HOST/JELLYFIN_API_KEY are accepted as aliases and fall back to the
# EMBY_ names. Either pair works with either backend value.
EMBY = os.environ.get("JELLYFIN_HOST", os.environ.get("EMBY_HOST", "")).rstrip("/")
EMBY_KEY = os.environ.get("JELLYFIN_API_KEY", os.environ.get("EMBY_API_KEY", ""))


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


def emby_billed_cast(people):
    """Top-billed actors, in one place, so the contract list and the saved
    headshot filenames (cast/N.jpg) share an index space."""
    return [p for p in (people or [])
            if p.get("Type") == "Actor" and p.get("Name")][:CAST_MAX]


def emby_download_cast(people):
    """Save headshots for the billed cast into output/cast/N.jpg."""
    for i, p in enumerate(emby_billed_cast(people)):
        if p.get("Id") and p.get("PrimaryImageTag"):
            try:
                emby_save_image(p["Id"], "Primary", f"cast/{i}.jpg", *HEADSHOT_PX)
            except Exception as e:
                print(f"emby cast art failed: {e}", flush=True)


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
    x = {"genres": [], "imdb": None, "stinger": [], "chapters": [], "cast": [],
         "poster": False, "backdrop": False, "logo": False}
    try:
        root = fetch_xml(f"/library/metadata/{rating_key}?includeRatings=1&includeChapters=1")
        item = root.find("./*")
        if item is not None:
            x["genres"] = [g.get("tag") for g in item.findall("Genre") if g.get("tag")]
            x["chapters"] = [int(c.get("startTimeOffset"))
                             for c in item.findall("Chapter")
                             if c.get("startTimeOffset") is not None]
            # one filtered list so x["cast"][i] lines up with cast/{i}.jpg
            roles = [r for r in item.findall("Role") if r.get("tag")][:CAST_MAX]
            x["cast"] = [{"name": r.get("tag"), "role": r.get("role") or "",
                          "thumb": bool(r.get("thumb"))} for r in roles]
            for i, r in enumerate(roles):
                if r.get("thumb"):
                    try:
                        transcode_to(f"cast/{i}.jpg", r.get("thumb"), *HEADSHOT_PX)
                    except Exception as e:
                        print(f"plex cast art failed: {e}", flush=True)
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
    if play.get("PlayMethod"):
        info["playMethod"] = play["PlayMethod"].lower()
    def _emby_stream(idx):
        if idx is None:
            return None
        s = next((m for m in streams if m.get("Index") == idx), None)
        return s.get("DisplayTitle") if s else None
    audio_track = _emby_stream(play.get("AudioStreamIndex"))
    subtitle_track = _emby_stream(play.get("SubtitleStreamIndex"))
    if audio_track:
        info["audioTrack"] = audio_track
    if subtitle_track:
        info["subtitleTrack"] = subtitle_track
    scores = {}
    if item.get("CommunityRating"):
        scores["imdb"] = round(float(item["CommunityRating"]), 1)
    if item.get("CriticRating") is not None:
        scores["rtCritic"] = round(float(item["CriticRating"]))
        scores["rtCriticFresh"] = float(item["CriticRating"]) >= 60
    if scores:
        info["scores"] = scores
    chapters = [emby_ticks_to_ms(c.get("StartPositionTicks"))
                for c in (item.get("Chapters") or [])]
    chapters = [c for c in chapters if c is not None]
    if chapters:
        info["chapters"] = chapters
    ud = item.get("UserData") or {}
    if "Played" in ud:
        info["watched"] = bool(ud.get("Played"))   # NOT PlayCount — verified
    if "IsFavorite" in ud:
        info["favorite"] = bool(ud.get("IsFavorite"))
    cast = [{"name": p["Name"], "role": p.get("Role") or "",
             "thumb": bool(p.get("PrimaryImageTag"))}
            for p in emby_billed_cast(item.get("People"))]
    if cast:
        info["cast"] = cast
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
    if a("viewCount") is not None:
        info["watched"] = int(a("viewCount") or 0) > 0
    if x["genres"]:
        info["genres"] = x["genres"][:3]
    if x["stinger"]:
        info["stinger"] = x["stinger"]
    info["poster"] = x["poster"]
    info["backdrop"] = x["backdrop"]
    info["logo"] = x["logo"]
    if x.get("chapters"):
        info["chapters"] = x["chapters"]
    if x.get("cast"):
        info["cast"] = x["cast"]
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
    part = media.find("Part") if media is not None else None
    if video.find("TranscodeSession") is not None:
        info["playMethod"] = "transcode"
    elif media is not None:
        decision = part.get("decision") if part is not None else None
        info["playMethod"] = {"copy": "directstream",
                              "transcode": "transcode"}.get(decision, "directplay")
    if part is not None:
        for stream in part.findall("Stream"):
            if stream.get("selected") != "1":
                continue
            label = stream.get("displayTitle") or stream.get("extendedDisplayTitle")
            if stream.get("streamType") == "2" and label:
                info["audioTrack"] = label
            elif stream.get("streamType") == "3" and label:
                info["subtitleTrack"] = label
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


def session_sort_key(user, device, title):
    """A total, case-insensitive order over sessions.

    /status/sessions has no defined order and Plex reorders it as sessions come
    and go, so "the first allowed session" is not a stable choice. Sorting first
    makes the pick deterministic: every poll, and every display, agrees.
    """
    return ((user or "").lower(), (device or "").lower(), (title or "").lower())


def clamp_rotate(value):
    """Rotation period in seconds: 0 disables, otherwise 5..3600."""
    try:
        seconds = int(value)
    except (TypeError, ValueError):
        return 30
    if seconds <= 0:
        return 0
    return max(5, min(3600, seconds))


def rotate_pick(items, seconds, now=None):
    """Which of several equally-allowed sessions drives the display right now.

    The choice is a pure function of the wall clock, so it needs no state and
    survives a restart mid-rotation. `seconds` <= 0 pins the first session.
    """
    if not items:
        return None
    if len(items) == 1 or seconds <= 0:
        return items[0]
    now = time.time() if now is None else now
    return items[int(now // seconds) % len(items)]


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

# The card page fetches /now-playing.json every POLL seconds. When it stops, the
# page is gone even if the display still reports the DashCast app as loaded.
# `at` is only ever set by a real request, so /healthz reports the truth. The
# startup grace window is tracked separately rather than by faking a poll --
# seeding `at` made a card that had never polled look alive.
LAST_CARD_POLL = {"at": 0.0}
CARD_GRACE = {"until": 0.0}
CARD_TIMEOUT = max(45, POLL * 6)


def card_alive(now, last_poll, timeout=CARD_TIMEOUT):
    """True when the card fetched now-playing.json recently enough."""
    return bool(last_poll) and (now - last_poll) < timeout


def card_ok(now, last_poll, grace_until, timeout=CARD_TIMEOUT):
    """Leave the display alone: the card is polling, or an already-cast page is
    still inside the grace window we give it to check in after a restart."""
    return card_alive(now, last_poll, timeout) or now < grace_until


def current_session():
    s = load_settings()
    users = filter_set(s.get("plexUsers"), ENV_USERS)
    devices = filter_set(s.get("plexDevices"), ENV_DEVICES)
    root = fetch_xml("/status/sessions")
    seen, allowed = [], []
    for video in root.findall("Video"):
        if video.get("type") not in ("movie", "episode"):
            continue
        u, d = session_names(video)
        title = video.get("title") or ""
        ok = session_allowed(video, users, devices)
        seen.append({"user": u, "device": d, "title": title, "allowed": ok})
        if ok:
            allowed.append((session_sort_key(u, d, title), video))
    LAST_SESSIONS[:] = seen
    # Sort before picking: the server's order is not stable, and without this
    # the card flips between two people's sessions on an arbitrary poll.
    allowed.sort(key=lambda pair: pair[0])
    picked = rotate_pick([video for _, video in allowed],
                         clamp_rotate(s.get("rotateSeconds")))
    return parse_session(picked) if picked is not None else None


def emby_session_names(s):
    """(user, device) display names for an Emby session; device falls back
    from DeviceName to Client, mirroring session_names() on the Plex path."""
    return (s.get("UserName") or "",
            s.get("DeviceName") or s.get("Client") or "")


def emby_session_allowed(s, users, devices):
    """True when the session's user AND device pass the allow-lists
    (an empty list allows everyone / any device)."""
    if users and (s.get("UserName") or "").lower() not in users:
        return False
    if devices:
        names = {(s.get(k) or "").lower()
                 for k in ("DeviceName", "Client")} - {""}
        if not (names & devices):
            return False
    return True


def emby_select_session(sessions, users, devices=frozenset()):
    """First session with a Movie/Episode NowPlayingItem whose user AND device
    pass the allow-lists (an empty list allows everyone / any device)."""
    for s in sessions:
        item = s.get("NowPlayingItem")
        if not item or item.get("Type") not in ("Movie", "Episode"):
            continue
        if not emby_session_allowed(s, users, devices):
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
    try:
        emby_download_cast(item.get("People") or [])
    except Exception as e:
        print(f"emby cast art failed: {e}", flush=True)
    if key:
        _emby_meta_cache.clear()  # only ever need the current item
        _emby_meta_cache[key] = x
    return x


def emby_enrich(item, user_id=None):
    """Fetch the fields /Sessions omits (People, UserData, and any missing
    genres/streams) from /Items once per title, cached, and merge in place."""
    key = item.get("Id")
    if not key:
        return
    if key not in _emby_enrich_cache:
        enriched = {}
        try:
            fields = ("Genres,MediaStreams,ProviderIds,Overview,OfficialRating,"
                      "CommunityRating,CriticRating,People,UserData,Taglines,Chapters")
            uid = f"&UserId={user_id}" if user_id else ""
            data = emby_fetch_json(f"/Items?Ids={key}{uid}&Fields={fields}")
            items = data.get("Items") if isinstance(data, dict) else None
            full = items[0] if items else {}
            for f in ("Genres", "MediaStreams", "ProviderIds", "Overview",
                      "OfficialRating", "CommunityRating", "CriticRating",
                      "People", "UserData", "Taglines", "Chapters"):
                if full.get(f) is None:
                    continue
                have = item.get(f)
                if isinstance(have, dict) and isinstance(full[f], dict):
                    # /Sessions can return a partial dict (e.g. UserData with only
                    # PlaybackPositionTicks). A truthy-but-partial dict must still
                    # gain the missing keys; values already on the session win.
                    merged = {**full[f], **have}
                    if merged != have:
                        enriched[f] = merged
                elif not have:
                    enriched[f] = full[f]
        except Exception as e:
            print(f"emby enrich failed: {e}", flush=True)
        _emby_enrich_cache.clear()  # only ever need the current item
        _emby_enrich_cache[key] = enriched
    item.update(_emby_enrich_cache[key])


def emby_current_session():
    settings = load_settings()
    users = filter_set(settings.get("plexUsers"), ENV_USERS)
    devices = filter_set(settings.get("plexDevices"), ENV_DEVICES)
    sessions = emby_fetch_json("/Sessions")
    seen, allowed = [], []
    for s in sessions:
        item = s.get("NowPlayingItem")
        if not item or item.get("Type") not in ("Movie", "Episode"):
            continue
        u, d = emby_session_names(s)
        title = item.get("Name") or ""
        ok = emby_session_allowed(s, users, devices)
        seen.append({"user": u, "device": d, "title": title, "allowed": ok})
        if ok:
            allowed.append((session_sort_key(u, d, title), s))
    LAST_SESSIONS[:] = seen
    # Emby's /Sessions order tracks activity, so "the first allowed session"
    # flipped between two people's titles on an arbitrary poll. Sort, then let
    # the clock decide whose turn it is.
    allowed.sort(key=lambda pair: pair[0])
    match = rotate_pick([session for _, session in allowed],
                        clamp_rotate(settings.get("rotateSeconds")))
    if match is None:
        return None
    emby_enrich(match.get("NowPlayingItem") or {}, user_id=match.get("UserId"))
    return parse_emby_session(match, extras=emby_extras)


def migrate_settings(raw):
    """Normalize any saved settings into the profile schema.

    Accepts the legacy flat object (appearance keys at top level), the current
    profile schema, or junk. Idempotent: migrating twice changes nothing.
    """
    if not isinstance(raw, dict):
        raw = {}
    out = {"default": "cast"}
    for k in GLOBAL_KEYS[1:]:        # hubIp, session filters, zip, rotation
        out[k] = coerce_global(k, raw.get(k, GLOBAL_DEFAULTS[k]))
    if raw.get("default") in PROFILES:
        out["default"] = raw["default"]

    saved = raw.get("profiles")
    saved = saved if isinstance(saved, dict) else {}
    # legacy flat appearance keys become the cast profile's starting point
    legacy = {k: v for k, v in raw.items()
              if k not in GLOBAL_KEYS and k != "profiles"}

    out["profiles"] = {}
    for name, seed in (("cast", profile_defaults("full")),
                       ("esp", profile_defaults("compact",
                                                orientation="portrait",
                                                template="onesheet"))):
        profile = dict(seed)
        source = saved.get(name)
        if isinstance(source, dict):
            profile.update({k: v for k, v in source.items() if k in seed})
        elif name == "cast":
            profile.update({k: v for k, v in legacy.items() if k in seed})
        out["profiles"][name] = profile
    return out


def resolve_settings(raw, profile=None):
    """Flatten the profile schema for one display: globals + that profile.

    Returns the same flat shape the card page and settings page have always
    consumed, so `?profile=` is the only thing a caller needs to know about.
    """
    if profile not in PROFILES:
        profile = raw.get("default", "cast")
    if profile not in PROFILES:
        profile = "cast"
    flat = {k: raw[k] for k in GLOBAL_KEYS[1:] if k in raw}
    flat.update(raw["profiles"][profile])
    return flat


def sanitize_profile(seed, body):
    """Validate a flat settings body into a complete profile dict."""
    p = dict(seed)
    p.update({k: v for k, v in body.items() if k in seed})
    if p["template"] not in TEMPLATES:
        p["template"] = "spotlight"
    if p["theme"] not in THEMES:
        p["theme"] = "amber"
    if p["titleFont"] not in TITLE_FONTS:
        p["titleFont"] = "system"
    if p["bodyFont"] not in TITLE_FONTS:
        p["bodyFont"] = "system"
    if p["posterSide"] not in ("left", "right"):
        p["posterSide"] = "right"
    if p["clockFormat"] not in ("12h", "24h"):
        p["clockFormat"] = "12h"
    if p["weatherUnits"] not in ("f", "c"):
        p["weatherUnits"] = "f"
    if p["density"] not in DENSITIES:
        p["density"] = "full"
    if p["orientation"] not in ORIENTATIONS:
        p["orientation"] = "auto"
    if not (isinstance(p["accent"], str)
            and (p["accent"] == "" or ACCENT_RE.match(p["accent"]))):
        p["accent"] = ""
    for key in seed:
        if key.startswith("show") or key in ("backdrop", "logo", "clockSeconds"):
            p[key] = bool(p[key])
    p["blockLayout"] = clean_block_layout(p["blockLayout"])
    return p


def save_settings(raw, body, profile=None):
    """Merge a flat settings body into `raw`: globals up top, appearance into
    the named profile. Other profiles are left untouched."""
    if profile not in PROFILES:
        profile = raw.get("default", "cast")
    if profile not in PROFILES:
        profile = "cast"
    out = {k: v for k, v in raw.items() if k != "profiles"}
    for k in GLOBAL_KEYS[1:]:
        out[k] = coerce_global(k, body.get(k, out.get(k, GLOBAL_DEFAULTS[k])))
    if not (out["hubIp"] == "" or IP_RE.match(out["hubIp"])):
        out["hubIp"] = ""
    out["weatherZip"] = out["weatherZip"].strip()[:10]
    out["profiles"] = dict(raw["profiles"])
    out["profiles"][profile] = sanitize_profile(raw["profiles"][profile], body)
    return out


def public_settings(raw, profile=None):
    """One profile's appearance, without the globals.

    /api/settings is CORS-enabled, so any page in the user's browser can read
    it. A display only needs to know how to draw itself; hubIp, the session
    filters, and weatherZip stay on the same-origin /settings.json.
    """
    return {k: v for k, v in resolve_settings(raw, profile).items()
            if k not in GLOBAL_KEYS}


def query_profile(path):
    """?profile=<name> from a request path, or None when absent/unknown."""
    query = urllib.parse.urlsplit(path).query
    name = urllib.parse.parse_qs(query).get("profile", [None])[0]
    return name if name in PROFILES else None


def load_raw_settings():
    """The on-disk profile schema, migrated and defaulted."""
    try:
        with open(SETTINGS_PATH) as f:
            return migrate_settings(json.load(f))
    except Exception:
        return migrate_settings({})


def load_settings(profile=None):
    """Flat settings for one display (default profile when unspecified)."""
    return resolve_settings(load_raw_settings(), profile)


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
            self._send(json.dumps(load_settings(query_profile(self.path))),
                       "application/json")
        elif path == "/devices":
            self._send(json.dumps(scan_devices("refresh" in self.path)),
                       "application/json")
        elif path == "/env-defaults":
            # Allowlisted container defaults, so the settings page can render a
            # blank field as "inheriting this" rather than "nothing is set".
            # Never CORS: this is same-origin only.
            self._send(json.dumps(env_defaults()), "application/json")
        elif path == "/weather":
            self._send(json.dumps(weather()), "application/json")
        elif path == "/sessions":
            self._send(json.dumps({"sessions": LAST_SESSIONS}), "application/json")
        elif path == "/healthz":
            last, now = LAST_CARD_POLL["at"], time.time()
            self._send(json.dumps({
                "ok": True, "version": VERSION,
                # Seconds since the card actually fetched now-playing.json; null
                # means it has never polled. A number climbing past CARD_TIMEOUT
                # is a display showing a dead page.
                "cardPollAgo": round(now - last, 1) if last else None,
                "cardAlive": card_alive(now, last),
                # True while a freshly cast page is still allowed to be silent.
                "cardGrace": now < CARD_GRACE["until"],
            }), "application/json")
        elif path in ("/now-playing.json", "/api/now-playing.json"):
            # Intentional read-only API for ESP32/ESPHome/HA consumers (CORS-enabled).
            # Serving it here rather than through the static fallthrough lets us
            # timestamp the card's heartbeat -- see card_alive().
            LAST_CARD_POLL["at"] = time.time()
            try:
                with open(JSON_PATH) as f:
                    body = f.read()
            except Exception:
                body = json.dumps({"playing": False})
            self._send(body, "application/json", cors=path.startswith("/api/"))
        elif path == "/api/settings":
            # Read-only, CORS-enabled: an ESP/ESPHome panel fetches the layout
            # and element visibility for its own profile. Appearance only --
            # see public_settings().
            self._send(json.dumps(public_settings(load_raw_settings(),
                                                  query_profile(self.path))),
                       "application/json", cors=True)
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
            updated = save_settings(load_raw_settings(), body,
                                    query_profile(self.path))
            atomic_write(SETTINGS_PATH, json.dumps(updated))
            self._send(json.dumps({"ok": True}), "application/json")
        except Exception as e:
            self._send(json.dumps({"ok": False, "error": str(e)}), "application/json", 400)


def serve_web():
    ThreadingHTTPServer(("", SERVE_PORT), WebHandler).serve_forever()


def loop():
    os.makedirs(DATA_DIR, exist_ok=True)
    if EMBY_FAMILY:
        host_name = "JELLYFIN_HOST" if BACKEND == "jellyfin" else "EMBY_HOST"
        key_name = "JELLYFIN_API_KEY" if BACKEND == "jellyfin" else "EMBY_API_KEY"
        required = (("PAGE_URL", PAGE_URL), (host_name, EMBY), (key_name, EMBY_KEY))
    else:
        required = (("PAGE_URL", PAGE_URL), ("PLEX_HOST", PLEX),
                    ("PLEX_TOKEN", TOKEN))
    missing = [name for name, value in required if not value]
    if missing:
        raise SystemExit("Missing required environment variables: " + ", ".join(missing))
    if not os.path.exists(SETTINGS_PATH):
        atomic_write(SETTINGS_PATH, json.dumps(migrate_settings({})))
    threading.Thread(target=serve_web, daemon=True).start()
    print(f"Marquee {VERSION} ready on :{SERVE_PORT} (card: /image, settings: /)",
          flush=True)
    # Grace period: an already-cast card gets one CARD_TIMEOUT window to check
    # in before we decide it is dead, so a restart does not re-cast needlessly.
    # This must not touch LAST_CARD_POLL -- /healthz would then report a card
    # that has never polled as alive.
    CARD_GRACE["until"] = time.time() + CARD_TIMEOUT
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
                    # "shown" only means the DashCast app is loaded. A display
                    # whose page died keeps reporting it, so the loop would sit
                    # there forever in front of a blank screen. The card's own
                    # heartbeat is the ground truth.
                    ok = card_ok(time.time(), LAST_CARD_POLL["at"],
                                 CARD_GRACE["until"])
                    if playing and not shown:
                        print(f"{BACKEND} playing ({info['title']}) -> showing",
                              flush=True)
                        device_show(PAGE_URL)
                        CARD_GRACE["until"] = time.time() + CARD_TIMEOUT
                    elif playing and not ok:
                        last = LAST_CARD_POLL["at"]
                        gone = (f"{time.time() - last:.0f}s" if last else "ever")
                        print(f"display claims to be showing but the card has "
                              f"not polled in {gone} -> re-casting", flush=True)
                        device_show(PAGE_URL)
                        CARD_GRACE["until"] = time.time() + CARD_TIMEOUT
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
  viewOffset="3600000" viewCount="2"
  tagline="She's back, and twice as fierce.">
  <Media videoResolution="1080" videoCodec="h264" audioCodec="eac3">
    <Part decision="directplay">
      <Stream streamType="2" selected="1" displayTitle="English (EAC3 5.1)"/>
      <Stream streamType="3" selected="1" displayTitle="English (SRT)"/>
    </Part>
  </Media>
  <Player state="paused"/></Video>"""

SAMPLE_EXTRAS = {"genres": ["Comedy", "Drama"], "imdb": 7.2, "stinger": ["after"],
                 "poster": True, "backdrop": True, "logo": True,
                 "chapters": [0, 300000, 600000],
                 "cast": [{"name": "Bill Skarsgard", "role": "Eddie", "thumb": True},
                          {"name": "Anthony Hopkins", "role": "William", "thumb": True}]}

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
        "UserData": {"Played": True, "IsFavorite": True, "PlayCount": 0},
        "MediaStreams": [
            {"Type": "Video", "Codec": "h264", "Height": 1080, "Width": 1920,
             "Index": 0, "DisplayTitle": "1080p H264"},
            {"Type": "Audio", "Codec": "eac3", "Index": 1,
             "DisplayTitle": "English EAC3 5.1 (Default)"},
            {"Type": "Subtitle", "Index": 2, "DisplayTitle": "English (SRT)"},
        ],
        "Chapters": [
            {"StartPositionTicks": 0, "Name": "Chapter 1"},
            {"StartPositionTicks": 3000000000, "Name": "Chapter 2"},
            {"StartPositionTicks": 6000000000, "Name": "Chapter 3"},
        ],
        "People": [
            {"Name": "Bill Skarsgard", "Role": "Eddie", "Type": "Actor",
             "Id": "10", "PrimaryImageTag": "aaa"},
            {"Name": "Anthony Hopkins", "Role": "William", "Type": "Actor",
             "Id": "11", "PrimaryImageTag": "bbb"},
            {"Name": "A Director", "Role": "", "Type": "Director", "Id": "12"},
        ],
    },
    "PlayState": {"PositionTicks": 36000000000, "IsPaused": True,
                  "PlayMethod": "DirectStream",
                  "AudioStreamIndex": 1, "SubtitleStreamIndex": 2},
}
SAMPLE_EMBY_EXTRAS = {"stinger": ["after"],
                      "poster": True, "backdrop": True, "logo": True}


def selftest():
    assert BACKEND in ("plex", "emby", "jellyfin")
    assert get_session is not None  # dispatcher exists and is chosen by BACKEND
    # Jellyfin rides the Emby session path; Plex does not.
    assert uses_emby_backend("emby") and uses_emby_backend("jellyfin")
    assert not uses_emby_backend("plex")
    info = parse_session(ET.fromstring(SAMPLE_SESSION), extras=lambda k, m: SAMPLE_EXTRAS)
    assert info["title"] == "The Devil Wears Prada 2"
    assert info["key"] == "79372"
    assert info["runtime"] == "1h 59m"
    assert info["media"] == "1080p · H264 · EAC3"
    assert info["scores"] == {"rtCritic": 77, "rtCriticFresh": True,
                              "rtAudience": 84, "rtAudienceFresh": True, "imdb": 7.2}
    assert info["genres"] == ["Comedy", "Drama"]
    assert info["playMethod"] == "directplay"
    assert info["audioTrack"] == "English (EAC3 5.1)"
    assert info["subtitleTrack"] == "English (SRT)"
    assert info["chapters"] == [0, 300000, 600000]
    assert info["tagline"] == "She's back, and twice as fierce."
    assert info["watched"] is True
    assert "favorite" not in info   # Plex has no favorite concept
    assert [c["name"] for c in info["cast"]] == ["Bill Skarsgard", "Anthony Hopkins"]
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
    # Every block the card page can position must be registered here, or
    # clean_block_layout() silently discards the user's drag on save.
    for block in ("tagline", "badges", "tracks", "cast"):
        assert block in EDITABLE_BLOCKS, block
    kept = clean_block_layout({"cast": {"x": 4}, "tagline": {"y": -2},
                               "nosuchblock": {"x": 1}})
    assert kept == {"cast": {"x": 4}, "tagline": {"y": -2}}
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

    # The settings page overrides the env var; it does not merge with it. A
    # union let PLEX_USERS filter sessions the UI showed no sign of, and no
    # amount of editing the field could lift it.
    assert filter_set("alice, Bob", "jamison") == {"alice", "bob"}
    assert filter_set("", "jamison") == {"jamison"}       # blank -> inherit env
    assert filter_set("   ", "jamison") == {"jamison"}    # whitespace is blank
    assert filter_set("alice", "") == {"alice"}
    assert filter_set("", "") == set()                    # nobody filtered
    assert "jamison" not in filter_set("alice", "jamison")  # env is replaced

    # The env hints the settings page may see are an allowlist. Nothing that
    # looks like a credential may ever join them.
    hints = env_defaults()
    assert set(hints) == set(ENV_HINT_KEYS), set(hints)
    for secret in ("PLEX_TOKEN", "EMBY_API_KEY", "TMDB_API_KEY", "token", "key"):
        assert not any(secret.lower() in k.lower() for k in hints), secret
    assert all(isinstance(v, str) for v in hints.values())

    # dashcast_active() only proves the DashCast *app* is loaded, not that our
    # card is drawing. A Hub whose page died keeps reporting DashCast forever,
    # so the loop never re-casts and the screen stays blank. The card polls
    # /now-playing.json every POLL seconds; silence means it is gone.
    assert card_alive(100.0, 99.0, 45)
    assert card_alive(100.0, 56.0, 45)          # just inside the window
    assert not card_alive(100.0, 54.0, 45)      # just outside
    assert not card_alive(100.0, 0.0, 45)       # never polled at all
    # ...and "never polled" stays dead even when the clock is younger than the
    # timeout, which a bare subtraction would misread as alive.
    assert not card_alive(10.0, 0.0, 45)

    # The startup grace window suppresses the re-cast, but it must never make a
    # card that has not polled *look* alive -- that hid a dead page on a Hub.
    assert card_ok(100.0, 0.0, grace_until=140.0, timeout=45)   # silent, in grace
    assert not card_alive(100.0, 0.0, 45)                       # ...but not alive
    assert not card_ok(100.0, 0.0, grace_until=0.0, timeout=45)  # grace expired
    assert card_ok(100.0, 99.0, grace_until=0.0, timeout=45)    # polling, no grace
    # a real poll keeps it ok long after grace has gone
    assert card_ok(1000.0, 999.0, grace_until=1.0, timeout=45)

    einfo = parse_emby_session(SAMPLE_EMBY_SESSION, extras=lambda item: SAMPLE_EMBY_EXTRAS)
    assert einfo["type"] == "movie"
    assert einfo["title"] == "The Devil Wears Prada 2"
    assert einfo["year"] == 2026
    assert einfo["state"] == "paused"
    assert einfo["runtime"] == "1h 59m"
    assert einfo["media"] == "1080p · H264 · EAC3"
    assert einfo["playMethod"] == "directstream"
    assert einfo["audioTrack"] == "English EAC3 5.1 (Default)"
    assert einfo["subtitleTrack"] == "English (SRT)"
    assert einfo["chapters"] == [0, 300000, 600000]
    assert einfo["progress"] == {"offsetMs": 3600000, "durationMs": 7141120}
    assert einfo["genres"] == ["Comedy", "Drama"]
    assert einfo["scores"] == {"imdb": 7.2, "rtCritic": 77, "rtCriticFresh": True}
    assert einfo["stinger"] == ["after"]
    assert einfo["poster"] and einfo["backdrop"] and einfo["logo"]
    assert einfo["tagline"] == "She's back, and twice as fierce."
    assert einfo["watched"] is True and einfo["favorite"] is True
    assert [c["name"] for c in einfo["cast"]] == ["Bill Skarsgard", "Anthony Hopkins"]
    assert einfo["cast"][0]["role"] == "Eddie"
    # the full enriched contract the card page and /api consumers rely on
    contract_keys = {"playing", "type", "key", "title", "year", "state",
                     "progress", "runtime", "summary", "contentRating", "genres",
                     "media", "scores", "poster", "backdrop", "logo",
                     "tagline", "playMethod", "audioTrack", "subtitleTrack",
                     "chapters", "watched", "favorite", "cast"}
    assert contract_keys.issubset(einfo), contract_keys - set(einfo)
    # Plex emits the same contract minus favorite (no such concept in Plex)
    minfo = parse_session(ET.fromstring(SAMPLE_SESSION), extras=lambda k, m: SAMPLE_EXTRAS)
    assert (contract_keys - {"favorite"}).issubset(minfo), \
        (contract_keys - {"favorite"}) - set(minfo)
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

    # device filters, matching the Plex path (v1.4.0 shipped them Plex-only)
    esessions = [
        {"UserName": "Alice", "DeviceName": "Chrome", "Client": "Emby Web",
         "NowPlayingItem": {"Type": "Movie", "Id": "1"}, "PlayState": {}},
        {"UserName": "Alice", "DeviceName": "Living Room TV",
         "Client": "Emby Theater",
         "NowPlayingItem": {"Type": "Movie", "Id": "2"}, "PlayState": {}},
    ]
    def pick(u, d):
        got = emby_select_session(esessions, u, d)
        return got and got["NowPlayingItem"]["Id"]
    assert pick(set(), set()) == "1"          # no filters -> first playable
    assert pick(set(), {"living room tv"}) == "2"   # by DeviceName
    assert pick(set(), {"emby theater"}) == "2"     # or by Client
    assert pick({"alice"}, {"chrome"}) == "1"       # user AND device must pass
    assert pick({"bob"}, {"chrome"}) is None
    assert pick(set(), {"nope"}) is None

    # Emby rotates too: /Sessions is ordered by activity, so without a sort the
    # card flips between two people's titles on an arbitrary poll.
    def emby_two(order):
        return [
            {"UserName": "Bob", "DeviceName": "Apple TV", "UserId": "b",
             "NowPlayingItem": {"Type": "Movie", "Id": "1", "Name": "Jaws"},
             "PlayState": {}},
            {"UserName": "alice", "DeviceName": "Pixel 9", "UserId": "a",
             "NowPlayingItem": {"Type": "Movie", "Id": "2", "Name": "Alien"},
             "PlayState": {}},
        ][::order]

    real_fetch, real_load, real_enrich = emby_fetch_json, load_settings, emby_enrich
    real_parse, real_time = parse_emby_session, time.time
    try:
        globals()["emby_enrich"] = lambda item, user_id=None: item
        globals()["parse_emby_session"] = lambda s, extras=None: {
            "title": (s.get("NowPlayingItem") or {}).get("Name")}
        globals()["load_settings"] = lambda profile=None: {
            "plexUsers": "", "plexDevices": "", "rotateSeconds": 30}
        picks = {}
        for label, order in (("normal", 1), ("flipped", -1)):
            globals()["emby_fetch_json"] = lambda _p, _o=order: emby_two(_o)
            for bucket, when in (("t0", 0.0), ("t1", 30.0)):
                globals()["time"].time = lambda _w=when: _w
                picks[(label, bucket)] = emby_current_session()["title"]
        # server order must not change the choice, and the clock must
        for bucket in ("t0", "t1"):
            assert picks[("normal", bucket)] == picks[("flipped", bucket)], picks
        assert picks[("normal", "t0")] == "Alien"      # alice sorts before Bob
        assert picks[("normal", "t1")] == "Jaws"
        assert len(LAST_SESSIONS) == 2                 # both still reported
    finally:
        globals()["time"].time = real_time
        globals()["emby_fetch_json"] = real_fetch
        globals()["load_settings"] = real_load
        globals()["emby_enrich"] = real_enrich
        globals()["parse_emby_session"] = real_parse

    # the settings page reads device names off LAST_SESSIONS, so Emby must
    # report them the way Plex does: DeviceName, falling back to Client
    assert emby_session_names(esessions[1]) == ("Alice", "Living Room TV")
    assert emby_session_names({"UserName": "Al", "Client": "Emby Web"}) == \
        ("Al", "Emby Web")
    assert emby_session_names({}) == ("", "")
    captured = {}
    def fake_fetch(path):
        captured["path"] = path
        return {"Items": [{
            "Genres": ["Horror"], "MediaStreams": [{"Type": "Video"}],
            "People": [{"Name": "Bill Skarsgard", "Role": "Eddie",
                        "Type": "Actor", "Id": "1", "PrimaryImageTag": "abc"}],
            "UserData": {"Played": True, "IsFavorite": True, "PlayCount": 0}}]}
    _orig_fetch = globals()["emby_fetch_json"]
    globals()["emby_fetch_json"] = fake_fetch
    try:
        _emby_enrich_cache.clear()
        it = {"Id": "999"}
        emby_enrich(it, user_id="u1")
        assert it["People"][0]["Name"] == "Bill Skarsgard"
        assert it["UserData"]["Played"] is True
        assert "UserId=u1" in captured["path"]
        assert "People" in captured["path"] and "UserData" in captured["path"]
        # a truthy-but-partial dict from /Sessions must still gain missing keys,
        # and values already on the session must win over the fetched ones
        _emby_enrich_cache.clear()
        partial = {"Id": "998", "UserData": {"PlaybackPositionTicks": 42,
                                             "IsFavorite": False}}
        emby_enrich(partial, user_id="u1")
        assert partial["UserData"]["Played"] is True        # merged in
        assert partial["UserData"]["PlaybackPositionTicks"] == 42  # session kept
        assert partial["UserData"]["IsFavorite"] is False   # session wins
    finally:
        globals()["emby_fetch_json"] = _orig_fetch
        _emby_enrich_cache.clear()
    saved = []
    _orig_save = globals()["emby_save_image"]
    globals()["emby_save_image"] = lambda item_id, kind, out, w, h: saved.append((item_id, kind, out))
    try:
        # index space is shared with the contract cast list: unnamed people are
        # filtered out of both, so cast[i] always matches cast/{i}.jpg
        emby_download_cast([
            {"Name": "Bill Skarsgard", "Id": "10", "PrimaryImageTag": "aaa", "Type": "Actor"},
            {"Name": "No Photo", "Id": "13", "Type": "Actor"},
            {"Name": "A Director", "Id": "14", "PrimaryImageTag": "ccc", "Type": "Director"}])
        assert ("10", "Primary", "cast/0.jpg") in saved
        assert not any(t[0] == "13" for t in saved)   # skipped: no image tag
        assert not any(t[0] == "14" for t in saved)   # skipped: not an actor
    finally:
        globals()["emby_save_image"] = _orig_save
    assert [p["Name"] for p in emby_billed_cast(
        [{"Name": "A", "Type": "Actor"}, {"Type": "Actor"},          # unnamed: dropped
         {"Name": "B", "Type": "Actor"}, {"Name": "D", "Type": "Director"}])] == ["A", "B"]
    assert TARGET in ("nest", "esp32")
    # Nest device functions exist and are the chosen dispatch
    assert device_available is not None and device_show is not None
    assert device_hide is not None and device_active is not None
    assert esp32_endpoint("10.0.0.5", 80, "display") == "http://10.0.0.5:80/display"
    assert esp32_endpoint("10.0.0.5", 8080, "stop") == "http://10.0.0.5:8080/stop"
    # The card's JSON url derived from PAGE_URL's origin
    assert esp32_json_url("http://192.168.1.10:8084/image") == \
        "http://192.168.1.10:8084/now-playing.json"
    assert "onesheet" in TEMPLATES
    assert set(PROFILES) == {"cast", "esp"}
    assert GLOBAL_KEYS == ("default", "hubIp", "plexUsers", "plexDevices",
                           "weatherZip", "rotateSeconds")
    # rotateSeconds is the one global that is not a string
    assert coerce_global("rotateSeconds", "45") == 45
    assert coerce_global("rotateSeconds", "junk") == 30
    assert coerce_global("rotateSeconds", 0) == 0
    assert coerce_global("hubIp", 12) == ""
    assert set(DENSITY_PRESETS) == {"full", "compact", "minimal"}
    assert DENSITY_PRESETS["full"]["showCast"] is True
    assert DENSITY_PRESETS["compact"]["showCast"] is False
    assert DENSITY_PRESETS["compact"]["showPlayMethod"] is True
    assert DENSITY_PRESETS["minimal"]["showPlot"] is False
    assert profile_defaults("full")["density"] == "full"
    assert profile_defaults("compact")["showTagline"] is False
    assert profile_defaults("minimal")["showProgress"] is True   # always-on element
    assert profile_defaults("full")["orientation"] == "auto"

    # Every flat setting must have a home, or migrating a user's saved file
    # would silently drop it. An upstream merge that adds a key trips this.
    homed = set(GLOBAL_KEYS) | set(PROFILE_BASE) | set(DENSITY_PRESETS["full"])
    assert not set(DEFAULT_SETTINGS) - homed, set(DEFAULT_SETTINGS) - homed

    # legacy flat settings migrate into profiles.cast; globals lift to top level
    legacy = {"hubIp": "10.0.0.5", "plexUsers": "alice", "plexDevices": "tv",
              "weatherZip": "90210", "bodyFont": "oswald", "showWeather": True,
              "template": "street", "theme": "concrete", "showPlot": False,
              "blockLayout": {"identity": {"x": 5}}}
    mig = migrate_settings(legacy)
    assert mig["default"] == "cast"
    assert mig["hubIp"] == "10.0.0.5" and mig["plexUsers"] == "alice"
    assert mig["weatherZip"] == "90210"          # one location, every profile
    assert mig["profiles"]["cast"]["bodyFont"] == "oswald"
    assert mig["profiles"]["cast"]["showWeather"] is True
    assert mig["profiles"]["esp"]["showWeather"] is False
    assert mig["profiles"]["cast"]["template"] == "street"
    assert mig["profiles"]["cast"]["theme"] == "concrete"
    assert mig["profiles"]["cast"]["showPlot"] is False
    assert mig["profiles"]["cast"]["blockLayout"] == {"identity": {"x": 5}}
    assert mig["profiles"]["cast"]["density"] == "full"
    # esp is seeded compact + portrait + onesheet, and does NOT inherit cast's theme
    assert mig["profiles"]["esp"]["density"] == "compact"
    assert mig["profiles"]["esp"]["orientation"] == "portrait"
    assert mig["profiles"]["esp"]["template"] == "onesheet"
    assert mig["profiles"]["esp"]["showCast"] is False
    # globals do not leak into profiles
    assert "hubIp" not in mig["profiles"]["cast"]
    # migrating an already-migrated dict is a no-op
    assert migrate_settings(mig) == mig
    # junk in, defaults out
    assert migrate_settings({})["profiles"]["cast"]["template"] == "spotlight"
    assert migrate_settings("not a dict")["default"] == "cast"

    # resolution merges globals over the chosen profile, flat, as callers expect
    raw = migrate_settings({"hubIp": "10.0.0.5", "theme": "crimson",
                            "weatherZip": "90210"})
    flat = resolve_settings(raw, "cast")
    assert flat["hubIp"] == "10.0.0.5"          # global
    assert flat["theme"] == "crimson"           # profile
    assert flat["density"] == "full"
    assert "profiles" not in flat and "default" not in flat
    esp = resolve_settings(raw, "esp")
    assert esp["template"] == "onesheet" and esp["orientation"] == "portrait"
    assert esp["hubIp"] == "10.0.0.5"           # globals shared by every profile
    # weather() reads weatherZip off the flat dict, from whichever profile
    assert flat["weatherZip"] == esp["weatherZip"] == "90210"
    # unknown / missing profile falls back to the default profile
    assert resolve_settings(raw, "bogus") == flat
    assert resolve_settings(raw, None) == flat
    # an explicit default is honored
    picked = migrate_settings({"default": "esp"})
    assert resolve_settings(picked, None)["template"] == "onesheet"

    # ?profile= picks a profile; anything unknown falls back to the default
    assert query_profile("/settings.json") is None
    assert query_profile("/settings.json?profile=esp") == "esp"
    assert query_profile("/api/settings?profile=cast&x=1") == "cast"
    assert query_profile("/api/settings?profile=bogus") is None
    assert query_profile("/api/settings?nope=1") is None

    # /api/settings is CORS-enabled, so it must not leak the globals:
    # the Hub's IP and the session filters are nobody else's business.
    pub = public_settings(raw, "esp")
    assert not set(GLOBAL_KEYS) & set(pub), set(GLOBAL_KEYS) & set(pub)
    assert pub["template"] == "onesheet"     # a panel still learns its layout
    assert pub["orientation"] == "portrait"
    assert pub["showCast"] is False

    # a save splits the settings page's flat body: globals up top, the rest
    # into the named profile, with every value validated
    base = migrate_settings({})
    body = {"hubIp": "10.0.0.9", "plexUsers": "bob", "theme": "bogus",
            "weatherZip": "  90210-1234567  ", "weatherUnits": "kelvin",
            "template": "onesheet", "density": "compact", "orientation": "portrait",
            "posterSide": "sideways", "titleFont": "comic", "bodyFont": "comic",
            "clockFormat": "25h", "accent": "red", "showCast": False,
            "showTagline": True, "showWeather": "yes", "clockSeconds": "yes",
            "blockLayout": {"identity": {"x": 5}, "bad": {}}}
    updated = save_settings(base, body, "esp")
    assert updated["hubIp"] == "10.0.0.9" and updated["plexUsers"] == "bob"
    assert updated["weatherZip"] == "90210-1234"   # trimmed and capped at 10
    esp = updated["profiles"]["esp"]
    assert esp["theme"] == "amber"            # invalid -> default
    assert esp["template"] == "onesheet"      # valid, and newly registered
    assert esp["density"] == "compact" and esp["orientation"] == "portrait"
    assert esp["posterSide"] == "right" and esp["titleFont"] == "system"
    assert esp["bodyFont"] == "system"        # upstream v1.6.0 key, validated
    assert esp["weatherUnits"] == "f"         # invalid -> default
    assert esp["clockFormat"] == "12h" and esp["accent"] == ""
    assert esp["showCast"] is False and esp["showTagline"] is True
    assert esp["showWeather"] is True         # coerced to bool
    assert esp["clockSeconds"] is True        # coerced to bool
    assert esp["blockLayout"] == {"identity": {"x": 5}}   # unknown block dropped
    # writing esp must not disturb cast
    assert updated["profiles"]["cast"] == base["profiles"]["cast"]
    # globals are never stored inside a profile
    assert not set(GLOBAL_KEYS) & set(esp)
    # a bad hubIp is rejected rather than stored
    assert save_settings(base, {"hubIp": "not-an-ip"}, "cast")["hubIp"] == ""
    # bad density/orientation fall back
    bad = save_settings(base, {"density": "huge", "orientation": "sideways"}, "cast")
    assert bad["profiles"]["cast"]["density"] == "full"
    assert bad["profiles"]["cast"]["orientation"] == "auto"
    # the card URL names the profile whose settings it should render
    assert profile_url("http://h:8084/image", "cast") == \
        "http://h:8084/image?profile=cast"
    assert profile_url("http://h:8084/image?x=1", "esp") == \
        "http://h:8084/image?x=1&profile=esp"
    # an explicit profile already in the URL is respected, not duplicated
    assert profile_url("http://h:8084/image?profile=esp", "cast") == \
        "http://h:8084/image?profile=esp"
    # nest_show appends "&cb=", so a separator must always be present already
    assert "?" in profile_url("http://h:8084/image", "cast")

    # a save is round-trippable: what you POST is what /settings.json serves
    assert resolve_settings(updated, "esp")["template"] == "onesheet"
    assert resolve_settings(updated, "esp")["hubIp"] == "10.0.0.9"
    # and the whole thing survives another migration untouched
    assert migrate_settings(updated) == updated


    # Several people can stream at once. /status/sessions has no defined order,
    # so picking "the first allowed session" made the card flip between them on
    # any poll where the server reordered. Sort, then rotate on a clock bucket.
    rows = [("Bob", "Apple TV", "Jaws"),
            ("alice", "Pixel 9", "Alien"),
            ("Bob", "apple tv", "Aliens")]
    assert sorted(rows, key=lambda r: session_sort_key(*r)) == [
        ("alice", "Pixel 9", "Alien"),
        ("Bob", "apple tv", "Aliens"),
        ("Bob", "Apple TV", "Jaws")]           # case-insensitive, total order

    items = ["a", "b", "c"]
    assert rotate_pick([], 30, now=0) is None
    assert rotate_pick(["solo"], 30, now=999) == "solo"
    # rotation is a pure function of the clock, so every display agrees
    assert rotate_pick(items, 30, now=0) == "a"
    assert rotate_pick(items, 30, now=29.9) == "a"    # stable within a bucket
    assert rotate_pick(items, 30, now=30) == "b"
    assert rotate_pick(items, 30, now=61) == "c"
    assert rotate_pick(items, 30, now=90) == "a"      # wraps
    # rotateSeconds = 0 disables rotation: the first session pins
    assert rotate_pick(items, 0, now=12345) == "a"
    assert rotate_pick(items, -5, now=12345) == "a"

    assert clamp_rotate(30) == 30 and clamp_rotate(0) == 0
    assert clamp_rotate("45") == 45                   # settings arrive as text
    assert clamp_rotate("nonsense") == 30 and clamp_rotate(None) == 30
    assert clamp_rotate(2) == 5 and clamp_rotate(99999) == 3600   # bounds

    # current_session() must not care what order the server lists sessions in.
    two = ('<MediaContainer>'
           '<Video type="movie" title="Alien" ratingKey="1">'
           '<User title="alice"/><Player title="Pixel 9"/></Video>'
           '<Video type="movie" title="Jaws" ratingKey="2">'
           '<User title="Bob"/><Player title="Apple TV"/></Video>'
           '</MediaContainer>')
    flipped = ('<MediaContainer>'
               '<Video type="movie" title="Jaws" ratingKey="2">'
               '<User title="Bob"/><Player title="Apple TV"/></Video>'
               '<Video type="movie" title="Alien" ratingKey="1">'
               '<User title="alice"/><Player title="Pixel 9"/></Video>'
               '</MediaContainer>')
    real_fetch, real_parse, real_load = fetch_xml, parse_session, load_settings
    real_time = time.time
    try:
        globals()["parse_session"] = lambda v: {"title": v.get("title")}
        globals()["load_settings"] = lambda: {"plexUsers": "", "plexDevices": "",
                                              "rotateSeconds": 30}
        picks = {}
        for label, xml in (("normal", two), ("flipped", flipped)):
            globals()["fetch_xml"] = lambda _p, _x=xml: ET.fromstring(_x)
            for bucket, when in (("t0", 0.0), ("t1", 30.0), ("t2", 60.0)):
                globals()["time"].time = lambda _w=when: _w
                picks[(label, bucket)] = current_session()["title"]
        # Server order must not change the choice...
        for bucket in ("t0", "t1", "t2"):
            assert picks[("normal", bucket)] == picks[("flipped", bucket)], \
                (bucket, picks)
        # ...and the clock, not the server, decides whose turn it is.
        assert picks[("normal", "t0")] == "Alien"      # alice sorts first
        assert picks[("normal", "t1")] == "Jaws"
        assert picks[("normal", "t2")] == "Alien"      # wraps
        assert len(LAST_SESSIONS) == 2                 # both still reported

        # rotateSeconds = 0 pins the first sorted session forever
        globals()["load_settings"] = lambda: {"plexUsers": "", "plexDevices": "",
                                              "rotateSeconds": 0}
        globals()["time"].time = lambda: 99999.0
        assert current_session()["title"] == "Alien"

        # a device filter narrows the candidates; rotation orders what is left
        globals()["load_settings"] = lambda: {"plexUsers": "", "plexDevices": "apple tv",
                                              "rotateSeconds": 30}
        globals()["time"].time = lambda: 0.0
        assert current_session()["title"] == "Jaws"
    finally:
        globals()["time"].time = real_time
        globals()["fetch_xml"] = real_fetch
        globals()["parse_session"] = real_parse
        globals()["load_settings"] = real_load
    print("selftest ok")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    else:
        loop()
