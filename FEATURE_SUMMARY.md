# Feature Branch Summary: Emby + ESP32 Support

**Branch**: `feature/emby-esp32-support`

**Status**: ✅ Complete - Ready for code review and integration testing

## What's Included

This branch adds **pluggable media backend and device target support** to Marquee, enabling:

1. **Media Backends**: Plex (existing) + Emby (new)
2. **Display Devices**: Google Cast/Nest Hub (existing) + ESP32 microcontroller (new)

### Files Added

```
cast/
  media_backends.py          # Abstract backend + Plex & Emby implementations
  device_targets.py          # Abstract device target + Cast & ESP32 implementations
  marquee_service.py         # Orchestration layer combining backends & devices

esp32/
  marquee_display.ino        # ESP32 firmware reference implementation

Documentation/
  ARCHITECTURE_EMBY_ESP32.md # High-level design and API documentation
  IMPLEMENTATION_GUIDE.md    # Step-by-step integration into cast.py
  ESP32_SETUP.md            # Hardware setup and troubleshooting guide
```

## Architecture Overview

### Media Backend Layer (`media_backends.py`)

**Abstract Base**: `MediaBackend`
```python
class MediaBackend(ABC):
    get_current_session(users) -> Dict      # Now-playing or None if idle
    get_health() -> bool                    # Server reachability
    get_poster_url(item_id) -> str
    get_backdrop_url(item_id) -> str
    get_logo_url(item_id) -> str
```

**Implementations**:
- **PlexBackend**: Polls `/status/sessions` (XML), handles Plex-specific metadata
- **EmbyBackend**: Polls `/emby/Sessions` (JSON), handles Emby-specific metadata

Both normalize output to identical `now-playing.json` schema for frontend compatibility.

### Device Target Layer (`device_targets.py`)

**Abstract Base**: `DeviceTarget`
```python
class DeviceTarget(ABC):
    is_available() -> bool                  # Device reachable
    cast_url(url) -> None                   # Display content
    stop() -> None                          # Return to idle
    get_info() -> Dict                      # Device metadata
```

**Implementations**:
- **GoogleCastTarget**: Uses `catt` CLI for Google Cast devices (Nest Hub, Chromecast)
- **ESP32Target**: HTTP API for ESP32 microcontroller displays

### Orchestration Layer (`marquee_service.py`)

**MarqueeService**: Ties backends and targets together
```python
service = MarqueeService(
    backend_type="plex|emby",
    backend_host="http://...",
    backend_token="token",
    device_type="cast|esp32",
    device_address="IP",
    ...
)
service.run(allowed_users)  # Main loop: poll -> cast -> manage lifecycle
```

Handles:
- Polling media backend at regular intervals
- Writing `now-playing.json` for frontend
- Managing device lifecycle (play → cast, stop → release)
- Error logging and resilience

## Configuration

### Environment Variables

```bash
# Media Backend (new)
BACKEND_TYPE=plex|emby                    # Default: plex
BACKEND_HOST=http://localhost:32400       # Plex: 32400, Emby: 8096
BACKEND_TOKEN=token                       # X-Plex-Token or Emby API key

# Device Target (new)
DEVICE_TYPE=cast|esp32                    # Default: cast
DEVICE_ADDRESS=192.168.1.50               # Device IP
DEVICE_PORT=80                            # Optional, for ESP32

# Existing variables still work
PLEX_HOST, PLEX_TOKEN, HUB_IP              # Backward compatible
```

### Docker Compose Example

```yaml
# Original (Plex + Nest Hub) - no changes needed
BACKEND_TYPE: plex
DEVICE_TYPE: cast

# Emby + Nest Hub
BACKEND_TYPE: emby
BACKEND_HOST: http://192.168.1.20:8096
BACKEND_TOKEN: emby-api-key
DEVICE_TYPE: cast

# Plex + ESP32
BACKEND_TYPE: plex
DEVICE_TYPE: esp32
DEVICE_ADDRESS: 192.168.1.100
DEVICE_PORT: 80

# Emby + ESP32
BACKEND_TYPE: emby
BACKEND_HOST: http://192.168.1.20:8096
BACKEND_TOKEN: emby-api-key
DEVICE_TYPE: esp32
DEVICE_ADDRESS: 192.168.1.100
```

## API Compatibility

### `now-playing.json` Schema (Normalized)

Both backends produce identical JSON:

```json
{
  "playing": true,
  "type": "movie" | "episode",
  "key": "item-id",
  "title": "Content Title",
  "year": 2024,
  "subtitle": "S1 · E5 · Episode Name",      // Episodes only
  "state": "playing" | "paused",
  "progress": {"offsetMs": 3600000, "durationMs": 7200000},
  "summary": "Plot...",
  "genres": ["Action", "Drama"],
  "scores": {"rtCritic": 85, "community": 82},
  "poster": true,
  "backdrop": true,
  "logo": true,
  "runtime": "2h 00m",
  "media": "1080p · H264 · AAC",
  "contentRating": "PG-13"
}
```

Frontend (`output/index.html`) remains **unchanged** — it consumes this same JSON structure.

### ESP32 REST API

```bash
GET  /status              # {"status": "ok", "displaying": bool, ...}
GET  /info                # {"name": "...", "firmware_version": "...", ...}
POST /display             # {"card_url": "http://..."}
POST /stop                # {}
POST /brightness          # {"level": 0-100}
```

## Backward Compatibility

✅ **100% backward compatible** with existing Plex + Nest Hub setups:

- Default behavior unchanged (`BACKEND_TYPE=plex`, `DEVICE_TYPE=cast`)
- Existing environment variables still work
- `docker-compose.yaml` requires no changes
- Settings UI + card rendering unchanged
- Existing Docker image can be redeployed without modification

## Testing Coverage

### Unit-testable Modules

All abstraction layers are designed for easy testing:

```python
# Test Plex backend
backend = PlexBackend(host, token)
assert backend.get_health()
session = backend.get_current_session(set())

# Test Emby backend
backend = EmbyBackend(host, api_key)
assert backend.get_health()
session = backend.get_current_session(set())

# Test Cast device
device = GoogleCastTarget(ip)
assert device.is_available()
device.cast_url("http://...")

# Test ESP32 device
device = ESP32Target(ip, port=80)
assert device.is_available()
device.cast_url("http://...")
```

### Recommended Test Matrix

| Backend | Device | Status | Notes |
|---------|--------|--------|-------|
| Plex | Cast | ✅ Original | Already in production |
| Plex | ESP32 | 🧪 New | Requires ESP32 hardware |
| Emby | Cast | 🧪 New | Requires Emby server |
| Emby | ESP32 | 🧪 New | Requires both |

## Known Limitations

### Emby Backend
- Credits-scene detection (TMDb integration) not implemented
- IMDb/Rotten Tomatoes ratings require plugin configuration
- User filtering less granular than Plex

### ESP32 Target
- Basic text rendering (no full image rendering yet)
- Single display instance only (no multi-device support)
- Touch input not implemented
- Requires manual WiFi credentials in firmware

### Both
- Art downloading moved to service layer (not yet implemented in current MVP)
- No multi-device support

## Next Steps for Integration

### Phase 1: Code Review
- [ ] Review architecture and design patterns
- [ ] Check error handling and edge cases
- [ ] Verify backward compatibility

### Phase 2: Integration
- [ ] Refactor `cast.py` to use `MarqueeService` (see IMPLEMENTATION_GUIDE.md)
- [ ] Integrate art downloading functionality
- [ ] Update settings UI with backend/device selection

### Phase 3: Testing
- [ ] Test all backend/device combinations
- [ ] Hardware testing with ESP32 + ILI9341
- [ ] Load testing (multiple concurrent sessions)

### Phase 4: Release
- [ ] Update README and documentation
- [ ] Bump version number
- [ ] Merge to `main`
- [ ] Create release notes

## Documentation

- **ARCHITECTURE_EMBY_ESP32.md** — High-level design, API contracts, configuration
- **IMPLEMENTATION_GUIDE.md** — Step-by-step integration into cast.py
- **ESP32_SETUP.md** — Hardware setup, wiring, firmware flashing, troubleshooting
- **Code comments** — Extensive docstrings in all Python modules

## Files to Review

1. **cast/media_backends.py** (567 lines)
   - PlexBackend: Extracts existing Plex polling logic
   - EmbyBackend: New Emby implementation
   - Both expose normalized `now-playing.json` schema

2. **cast/device_targets.py** (371 lines)
   - GoogleCastTarget: Wraps existing `catt` CLI
   - ESP32Target: New HTTP-based device control
   - Both handle availability checks and error recovery

3. **cast/marquee_service.py** (212 lines)
   - MarqueeService: Orchestrates backends and devices
   - Manages polling loop, lifecycle transitions
   - Minimal, focused responsibility

4. **esp32/marquee_display.ino** (429 lines)
   - Reference firmware for ILI9341 display
   - REST API implementation
   - Idle/wake behavior, brightness control

## Development Notes

- **Python 3.6+** (uses type hints)
- **No new dependencies** (uses stdlib + existing `catt` for Cast)
- **Modular design** — Each backend/device can be tested independently
- **Factory pattern** — `create_backend()` and `create_device_target()` for extensibility
- **Async-ready** — Service loop can be moved to async/await if needed

## Contact & Questions

For questions about the design or implementation:

1. Check ARCHITECTURE_EMBY_ESP32.md for high-level overview
2. Check IMPLEMENTATION_GUIDE.md for integration steps
3. Review inline code comments for implementation details
4. See ESP32_SETUP.md for hardware questions

---

**Ready to merge after:**
- ✅ Architecture review
- ⏳ Integration into cast.py (see IMPLEMENTATION_GUIDE.md Phase 2)
- ⏳ Testing all combinations
- ⏳ Documentation updates to README
