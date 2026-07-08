# Implementation Guide: Emby + ESP32 Integration

This guide walks through integrating the new abstraction layers into the existing `cast/cast.py` main service.

## Phase 1: Refactor Existing cast.py

### 1.1 Extract Plex polling into PlexBackend

Move these functions from `cast.py` to `media_backends.py` (already done in `PlexBackend`):
- `plex_url()`
- `fetch_xml()`
- `library_extras()`
- `parse_session()`
- `current_session()`
- `tmdb_stinger()`
- `download_art()` (move to service layer)

**Status**: ✅ Complete in `media_backends.py`

### 1.2 Extract Google Cast control into GoogleCastTarget

Move these functions from `cast.py` to `device_targets.py` (already done in `GoogleCastTarget`):
- `catt()`
- `dashcast_active()`
- `scan_devices()` (move to service layer for device discovery)

**Status**: ✅ Complete in `device_targets.py`

### 1.3 Create MarqueeService integration

The new `MarqueeService` class orchestrates polling and casting. The updated `cast.py` will:

1. Parse environment variables for backend/device type
2. Create backend + device via factories
3. Instantiate `MarqueeService`
4. Keep existing HTTP server (settings UI, card serving)
5. Run service loop in background thread

**Status**: ✅ `marquee_service.py` ready

## Phase 2: Update cast.py (Main Entry Point)

The existing `cast.py` needs minimal changes:

```python
# OLD (Plex-only):
while True:
    try:
        info = current_session()  # Direct Plex poll
        atomic_write(JSON_PATH, json.dumps(info or {"playing": False}))
        playing = bool(info)
        if playing != last_playing or tick % 6 == 0:
            if playing:
                catt("cast_site", PAGE_URL)  # Direct catt call
            elif last_playing:
                catt("stop")
        last_playing = playing
        tick += 1
    except Exception as e:
        print(f"loop error: {e}", flush=True)
    time.sleep(POLL)

# NEW (pluggable):
service = MarqueeService(
    backend_type=os.environ.get("BACKEND_TYPE", "plex"),
    backend_host=os.environ.get("BACKEND_HOST", PLEX),
    backend_token=os.environ.get("BACKEND_TOKEN", TOKEN),
    device_type=os.environ.get("DEVICE_TYPE", "cast"),
    device_address=os.environ.get("DEVICE_ADDRESS", HUB_IP),
    device_port=os.environ.get("DEVICE_PORT"),
    poll_seconds=POLL,
    output_dir=OUTPUT,
    data_dir=DATA_DIR,
    page_url=PAGE_URL,
)
service.run(USERS)
```

### Changes to cast.py

1. **Add imports** at top:
   ```python
   from marquee_service import MarqueeService
   from media_backends import create_backend
   from device_targets import create_device_target
   ```

2. **Extend environment parsing**:
   ```python
   BACKEND_TYPE = os.environ.get("BACKEND_TYPE", "plex")
   BACKEND_HOST = os.environ.get("BACKEND_HOST", PLEX)
   BACKEND_TOKEN = os.environ.get("BACKEND_TOKEN", TOKEN)
   DEVICE_TYPE = os.environ.get("DEVICE_TYPE", "cast")
   DEVICE_ADDRESS = os.environ.get("DEVICE_ADDRESS", HUB_IP)
   DEVICE_PORT = os.environ.get("DEVICE_PORT")
   ```

3. **Update loop() function**:
   - Replace the while loop with `MarqueeService` instantiation and call to `.run()`
   - Keep the `serve_web()` thread unchanged (still serves settings UI and card)
   - Add a `/status` endpoint to `WebHandler` that calls `service.get_status()`

4. **Keep backward compatibility**:
   - Default `BACKEND_TYPE="plex"` and `DEVICE_TYPE="cast"`
   - Existing env vars (`PLEX_HOST`, `PLEX_TOKEN`, `HUB_IP`) still work
   - No breaking changes to docker-compose.yaml

**Location to edit**: `cast/cast.py` lines 394-433 (the `loop()` function)

## Phase 3: Update Settings UI (Optional but Recommended)

The `cast/settings.html` could add a "Backend & Device" section:

```html
<div class="settings-group">
  <h3>Backend & Device</h3>
  
  <label>
    Media Server Type:
    <select id="backendType" name="backendType">
      <option value="plex">Plex</option>
      <option value="emby">Emby</option>
    </select>
  </label>
  
  <label>
    Display Device:
    <select id="deviceType" name="deviceType">
      <option value="cast">Google Cast (Nest Hub)</option>
      <option value="esp32">ESP32 Display</option>
    </select>
  </label>
  
  <!-- Plex-specific -->
  <div id="plex-settings" class="backend-specific">
    <label>Plex Token: <input type="password" name="plexToken" /></label>
  </div>
  
  <!-- Emby-specific -->
  <div id="emby-settings" class="backend-specific" style="display:none">
    <label>Emby Host: <input type="text" name="embyHost" placeholder="http://localhost:8096" /></label>
    <label>Emby API Key: <input type="password" name="embyKey" /></label>
  </div>
  
  <!-- ESP32-specific -->
  <div id="esp32-settings" class="device-specific" style="display:none">
    <label>ESP32 IP: <input type="text" name="esp32Ip" placeholder="192.168.1.100" /></label>
    <label>ESP32 Port: <input type="number" name="esp32Port" placeholder="80" value="80" /></label>
  </div>
</div>
```

Then in JavaScript:
- Load current backend/device type from `/settings.json`
- Show/hide fields based on selection
- Save to settings and restart service (or hot-reload)

**Location**: `cast/settings.html` (add new section)

## Phase 4: Docker & Deployment

### Update compose.yaml

Add example configurations as comments:

```yaml
services:
  marquee:
    build: .
    image: marquee:local
    network_mode: host
    restart: unless-stopped
    environment:
      # === Media Backend ===
      # BACKEND_TYPE: plex          # default: plex
      # BACKEND_HOST: http://localhost:32400
      # BACKEND_TOKEN: your-plex-token
      
      # Uncomment for Emby:
      # BACKEND_TYPE: emby
      # BACKEND_HOST: http://192.168.1.20:8096
      # BACKEND_TOKEN: your-emby-api-key
      
      # === Display Device ===
      # DEVICE_TYPE: cast           # default: cast
      # DEVICE_ADDRESS: 192.168.1.50
      
      # Uncomment for ESP32:
      # DEVICE_TYPE: esp32
      # DEVICE_ADDRESS: 192.168.1.100
      # DEVICE_PORT: 80
      
      # === Service ===
      PAGE_URL: http://192.168.1.10:8084/image
      POLL_SECONDS: 5
      PLEX_USERS: ""              # comma-separated, empty = all
    volumes:
      - ./data:/config
```

### requirements.txt

No new Python dependencies needed. Existing:
- `catt` (for Google Cast)
- Standard library for HTTP/JSON/subprocess

## Phase 5: Testing Checklist

### Plex + Nest Hub (Original)
- [ ] Start with no new env vars
- [ ] Verify Plex polling works
- [ ] Verify Cast device discovery
- [ ] Verify card displays on Hub
- [ ] Verify playback transitions

### Emby + Nest Hub
- [ ] Set `BACKEND_TYPE=emby`, `BACKEND_HOST=http://emby:8096`, `BACKEND_TOKEN=key`
- [ ] Verify Emby session polling
- [ ] Verify Cast still works
- [ ] Verify card displays metadata from Emby

### Plex + ESP32
- [ ] Flash ESP32 firmware
- [ ] Set `DEVICE_TYPE=esp32`, `DEVICE_ADDRESS=192.168.1.100`
- [ ] Verify ESP32 API reachable (`curl http://192.168.1.100/status`)
- [ ] Verify Marquee sends card URL to ESP32
- [ ] Verify ESP32 displays card (basic rendering)

### Emby + ESP32
- [ ] Combine all settings
- [ ] Verify end-to-end: Emby → Marquee → ESP32

## Phase 6: Documentation

### Update README.md

Add a section:

```markdown
## Media Servers & Displays

Marquee now supports:

**Media Servers:**
- Plex (default)
- Emby

**Display Devices:**
- Google Nest Hub / Chromecast (default)
- ESP32 microcontroller

Set `BACKEND_TYPE` and `DEVICE_TYPE` to choose. See [ARCHITECTURE_EMBY_ESP32.md](ARCHITECTURE_EMBY_ESP32.md) for details.
```

### API Reference

Document the new env vars in README's Configuration section.

## Implementation Order

**For MVP (minimal viable product):**

1. ✅ Create abstraction layers (`media_backends.py`, `device_targets.py`, `marquee_service.py`)
2. ✅ Implement Plex and Emby backends
3. ✅ Implement Google Cast and ESP32 targets
4. ✅ Write ESP32 firmware reference
5. ✅ Document architecture
6. **TODO**: Refactor `cast.py` to use `MarqueeService` (backward-compatible)
7. **TODO**: Test all combinations
8. **TODO**: Update README and compose.yaml
9. **TODO**: Optional: Settings UI updates

## Rollback Plan

If issues arise:

1. Revert to `main` branch (original Plex + Cast only)
2. Feature branch remains available for bugfixes
3. Can gradually merge to main after thorough testing

## FAQ

**Q: Will existing Plex + Nest Hub setups break?**
A: No. Default behavior is unchanged. Just redeploy the container.

**Q: How do I switch backends mid-deployment?**
A: Update env vars and restart the container. Settings persist in `/config/settings.json`.

**Q: Does ESP32 need the full Marquee server?**
A: Yes, but the server just needs to be accessible via HTTP. The ESP32 doesn't require Docker—just the microcontroller and a network connection.

**Q: Can I run multiple ESP32 devices?**
A: Not yet—`MarqueeService` currently manages one device. Multi-device support is a future enhancement.
