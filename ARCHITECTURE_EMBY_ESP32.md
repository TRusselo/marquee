# Emby + ESP32 Support

This branch adds support for **Emby media servers** (in addition to Plex) and **ESP32 microcontroller displays** (in addition to Google Nest Hubs).

## Architecture

The codebase now uses a **pluggable backend/device pattern** to support multiple combinations:

```
┌─────────────────────────────┐
│   Media Backend             │
├─────────────────────────────┤
│  Plex     │  Emby          │
│  (XML)    │  (JSON)        │
└──────────────┬──────────────┘
               │
         ┌─────▼──────┐
         │ MarqueeService
         │ (orchestrates)
         └─────┬──────┘
               │
┌──────────────▼──────────────┐
│   Device Target             │
├─────────────────────────────┤
│  Google Cast (catt) │ ESP32 (HTTP) │
│  (DashCast)         │ (polling)    │
└─────────────────────────────┘
```

## New Modules

### `cast/media_backends.py`

Abstract media server interface with two implementations:

- **`PlexBackend`**: Polls Plex `/status/sessions` (XML), fetches metadata, handles art transcoding
- **`EmbyBackend`**: Polls Emby `/emby/Sessions` (JSON), fetches metadata via `/emby/Items/{id}`

Both expose:
- `get_current_session(users)` → now-playing dict
- `get_health()` → server reachability
- Art URL getters (`get_poster_url`, `get_backdrop_url`, `get_logo_url`)

### `cast/device_targets.py`

Abstract device target interface with two implementations:

- **`GoogleCastTarget`**: Uses `catt` CLI for Google Cast devices (Nest Hub, Chromecast, etc.)
  - `cast_url(url)` → casts via DashCast
  - `stop()` → releases device
  - `dashcast_active()` → checks if DashCast is running

- **`ESP32Target`**: HTTP API for ESP32 microcontroller displays
  - `cast_url(url)` → POSTs card URL to ESP32; device polls and renders locally
  - `stop()` → clears display
  - `set_brightness(level)` → controls backlight

Both expose:
- `is_available()` → device reachability
- `get_info()` → device metadata

### `cast/marquee_service.py`

Orchestration layer that ties backends and targets together:

- Polls media backend at regular intervals
- Writes `now-playing.json` for frontend consumption
- Manages device lifecycle (cast on play, release on stop, reconciliation)
- Logs transitions and errors

### `esp32/marquee_display.ino`

Reference ESP32 firmware for rendering Marquee cards on a microcontroller display (ILI9341):

- WiFi setup
- REST API: `/status`, `/info`, `/display`, `/stop`, `/brightness`
- Fetches card HTML and renders basic now-playing info
- Idle/wake behavior (dims after inactivity, brightens on new content)

## Configuration

### Environment Variables

New variables (in addition to existing `PLEX_*` env vars):

```bash
# Media backend (default: plex)
BACKEND_TYPE=plex|emby
BACKEND_HOST=http://localhost:32400          # Plex: 32400, Emby: 8096
BACKEND_TOKEN=X-Plex-Token-OR-Emby-API-key

# Device target (default: cast)
DEVICE_TYPE=cast|esp32
DEVICE_ADDRESS=192.168.1.50                 # Device IP
DEVICE_PORT=80                              # Optional, for ESP32

# Service
POLL_SECONDS=5                              # Polling interval
```

### Docker Compose Example

```yaml
services:
  marquee:
    build: .
    image: marquee:local
    network_mode: host
    environment:
      # Plex + Nest Hub (original)
      BACKEND_TYPE: plex
      BACKEND_HOST: http://localhost:32400
      BACKEND_TOKEN: plex-token-here
      DEVICE_TYPE: cast
      DEVICE_ADDRESS: 192.168.1.50
      PAGE_URL: http://192.168.1.10:8084/image
      PLEX_USERS: ""  # empty = everyone
      
      # OR: Emby + ESP32
      # BACKEND_TYPE: emby
      # BACKEND_HOST: http://localhost:8096
      # BACKEND_TOKEN: emby-api-key-here
      # DEVICE_TYPE: esp32
      # DEVICE_ADDRESS: 192.168.1.100
      # DEVICE_PORT: 80
      # PAGE_URL: http://192.168.1.10:8084/image
    volumes:
      - ./data:/config
```

## Usage

### Starting with Plex + Nest Hub (no changes)

```bash
docker compose up -d --build
```

Existing configuration still works — `BACKEND_TYPE` and `DEVICE_TYPE` default to `plex` and `cast`.

### Switching to Emby

1. Add to `compose.yaml`:
   ```yaml
   BACKEND_TYPE: emby
   BACKEND_HOST: http://192.168.1.20:8096
   BACKEND_TOKEN: your-emby-api-key
   ```
2. Restart: `docker compose up -d --build`

### Switching to ESP32

1. Flash ESP32 with `esp32/marquee_display.ino` firmware
   - Set WiFi credentials in sketch
   - Configure TFT_eSPI for your display in `User_Setup.h`
   - Upload via Arduino IDE or PlatformIO

2. Update `compose.yaml`:
   ```yaml
   DEVICE_TYPE: esp32
   DEVICE_ADDRESS: 192.168.1.100  # ESP32 IP
   DEVICE_PORT: 80
   ```
3. Restart: `docker compose up -d --build`

### Combining Emby + ESP32

```yaml
BACKEND_TYPE: emby
BACKEND_HOST: http://192.168.1.20:8096
BACKEND_TOKEN: your-emby-api-key
DEVICE_TYPE: esp32
DEVICE_ADDRESS: 192.168.1.100
DEVICE_PORT: 80
```

## API Compatibility

### `now-playing.json`

Both backends produce a normalized JSON structure:

```json
{
  "playing": true,
  "type": "movie",
  "key": "item-id",
  "title": "Movie Title",
  "year": 2024,
  "subtitle": "S1 · E5 · Episode Name",  // Episodes only
  "state": "playing",
  "progress": {
    "offsetMs": 3600000,
    "durationMs": 7200000
  },
  "summary": "Plot description...",
  "genres": ["Action", "Drama"],
  "scores": {
    "rtCritic": 85,
    "community": 82
  },
  "poster": true,
  "backdrop": true,
  "logo": true,
  "runtime": "2h 00m",
  "media": "1080p · H264 · AAC",
  "contentRating": "PG-13"
}
```

The frontend (HTML/CSS/JS in `output/index.html`) remains unchanged — it still consumes this JSON.

## Testing

### Plex Backend

```bash
python3 -c "
from cast.media_backends import PlexBackend
backend = PlexBackend('http://localhost:32400', 'your-token')
print('Health:', backend.get_health())
session = backend.get_current_session(set())
print('Session:', session)
"
```

### Emby Backend

```bash
python3 -c "
from cast.media_backends import EmbyBackend
backend = EmbyBackend('http://localhost:8096', 'your-api-key')
print('Health:', backend.get_health())
session = backend.get_current_session(set())
print('Session:', session)
"
```

### ESP32 Device

```bash
# Query device status
curl http://192.168.1.100/status

# Display a card
curl -X POST http://192.168.1.100/display \
  -H 'Content-Type: application/json' \
  -d '{"card_url": "http://192.168.1.10:8084/image"}'

# Stop display
curl -X POST http://192.168.1.100/stop

# Set brightness (0-100)
curl -X POST http://192.168.1.100/brightness \
  -H 'Content-Type: application/json' \
  -d '{"level": 75}'
```

## Development

### Adding a New Backend

1. Subclass `MediaBackend` in `cast/media_backends.py`
2. Implement required methods (see `PlexBackend` and `EmbyBackend`)
3. Update `create_backend()` factory
4. Normalize session output to match `now-playing.json` schema

### Adding a New Device

1. Subclass `DeviceTarget` in `cast/device_targets.py`
2. Implement required methods (see `GoogleCastTarget` and `ESP32Target`)
3. Update `create_device_target()` factory

## Known Limitations

### Emby
- Credits-scene detection (TMDb stinger) not implemented yet
- IMDb/Rotten Tomatoes ratings via Emby plugins would need custom integration
- Emby's user filtering less granular than Plex (no per-session user check yet)

### ESP32
- Basic HTML rendering (text + progress bar); no image rendering yet
- Single display instance (no multi-device support yet)
- Touch input not implemented
- Requires manual WiFi credentials in firmware

## Next Steps

- [ ] Integrate into main `cast/cast.py` (refactor existing Plex polling)
- [ ] Update Web UI settings to allow backend/device selection
- [ ] Add ESP32 brightness/settings persistence
- [ ] Full image rendering on ESP32 (poster, backdrop caching)
- [ ] Multi-device support (multiple ESP32 or Cast devices)
- [ ] Enhanced Emby metadata (TMDb, user filtering, plugins)
- [ ] Health check dashboard
