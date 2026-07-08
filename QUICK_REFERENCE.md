# Quick Reference: Emby + ESP32 Support

Fast lookup for common tasks and configurations.

## Configuration Cheat Sheet

### Plex + Nest Hub (Original)
```yaml
environment:
  BACKEND_TYPE: plex
  PLEX_HOST: http://localhost:32400
  PLEX_TOKEN: your-plex-token
  DEVICE_TYPE: cast
  HUB_IP: 192.168.1.50
  PAGE_URL: http://192.168.1.10:8084/image
```

### Emby + Nest Hub
```yaml
environment:
  BACKEND_TYPE: emby
  BACKEND_HOST: http://192.168.1.20:8096
  BACKEND_TOKEN: your-emby-api-key
  DEVICE_TYPE: cast
  DEVICE_ADDRESS: 192.168.1.50
  PAGE_URL: http://192.168.1.10:8084/image
```

### Plex + ESP32
```yaml
environment:
  BACKEND_TYPE: plex
  PLEX_HOST: http://localhost:32400
  PLEX_TOKEN: your-plex-token
  DEVICE_TYPE: esp32
  DEVICE_ADDRESS: 192.168.1.100
  DEVICE_PORT: 80
  PAGE_URL: http://192.168.1.10:8084/image
```

### Emby + ESP32
```yaml
environment:
  BACKEND_TYPE: emby
  BACKEND_HOST: http://192.168.1.20:8096
  BACKEND_TOKEN: your-emby-api-key
  DEVICE_TYPE: esp32
  DEVICE_ADDRESS: 192.168.1.100
  DEVICE_PORT: 80
  PAGE_URL: http://192.168.1.10:8084/image
```

## ESP32 Testing

### Verify Connectivity
```bash
curl http://192.168.1.100/status
```

### Display Content
```bash
curl -X POST http://192.168.1.100/display \
  -H 'Content-Type: application/json' \
  -d '{"card_url": "http://192.168.1.10:8084/image"}'
```

### Set Brightness (0-100)
```bash
curl -X POST http://192.168.1.100/brightness \
  -H 'Content-Type: application/json' \
  -d '{"level": 75}'
```

### Stop Display
```bash
curl -X POST http://192.168.1.100/stop
```

## Docker Commands

### Build and Start
```bash
docker compose up -d --build
```

### View Logs
```bash
docker compose logs -f marquee
```

### Restart Service
```bash
docker compose restart marquee
```

### Stop Service
```bash
docker compose down
```

## Python Testing

### Test Plex Backend
```python
from cast.media_backends import PlexBackend

backend = PlexBackend('http://localhost:32400', 'your-token')
print('Healthy:', backend.get_health())
session = backend.get_current_session(set())
print('Now playing:', session)
```

### Test Emby Backend
```python
from cast.media_backends import EmbyBackend

backend = EmbyBackend('http://localhost:8096', 'your-api-key')
print('Healthy:', backend.get_health())
session = backend.get_current_session(set())
print('Now playing:', session)
```

### Test Cast Device
```python
from cast.device_targets import GoogleCastTarget

device = GoogleCastTarget('192.168.1.50')
print('Available:', device.is_available())
device.cast_url('http://192.168.1.10:8084/image')
```

### Test ESP32 Device
```python
from cast.device_targets import ESP32Target

device = ESP32Target('192.168.1.100', 80)
print('Available:', device.is_available())
device.cast_url('http://192.168.1.10:8084/image')
device.set_brightness(75)
```

## Environment Variables Reference

| Variable | Type | Default | Notes |
|----------|------|---------|-------|
| `BACKEND_TYPE` | string | `plex` | `plex` or `emby` |
| `BACKEND_HOST` | string | `http://localhost:32400` | Plex: 32400, Emby: 8096 |
| `BACKEND_TOKEN` | string | (required) | X-Plex-Token or Emby API key |
| `DEVICE_TYPE` | string | `cast` | `cast` or `esp32` |
| `DEVICE_ADDRESS` | string | (from HUB_IP) | Device IP address |
| `DEVICE_PORT` | int | 80 | Used for ESP32 only |
| `PAGE_URL` | string | (required) | Server URL for casting |
| `POLL_SECONDS` | int | 5 | Polling interval |
| `PLEX_USERS` | string | (empty) | Comma-separated usernames |
| `PLEX_HOST` | string | (legacy) | Backward compat for Plex |
| `PLEX_TOKEN` | string | (legacy) | Backward compat for Plex |
| `HUB_IP` | string | (legacy) | Backward compat for Cast |

## File Structure

```
marquee/
├── cast/
│   ├── cast.py                    (main entry point)
│   ├── settings.html              (UI)
│   ├── media_backends.py          (NEW: Plex/Emby abstraction)
│   ├── device_targets.py          (NEW: Cast/ESP32 abstraction)
│   └── marquee_service.py         (NEW: orchestration)
├── output/
│   ├── index.html                 (card template)
│   └── now-playing.json           (generated)
├── esp32/
│   └── marquee_display.ino        (NEW: firmware)
├── docs/
├── compose.yaml
├── Dockerfile
├── requirements.txt
├── ARCHITECTURE_EMBY_ESP32.md     (NEW: design)
├── IMPLEMENTATION_GUIDE.md        (NEW: integration)
├── ESP32_SETUP.md                 (NEW: hardware)
├── FEATURE_SUMMARY.md             (NEW: overview)
└── QUICK_REFERENCE.md             (NEW: this file)
```

## Troubleshooting Matrix

### Service won't start
- Check logs: `docker compose logs marquee`
- Verify env vars are set correctly
- Ensure media server is reachable: `curl $BACKEND_HOST`

### Device unreachable
- Verify device IP: `ping $DEVICE_ADDRESS`
- Check on same network as Marquee server
- For Cast: Verify `catt scan` finds device
- For ESP32: Check WiFi connection in serial monitor

### No content displayed
- Verify content is actually playing
- Check `now-playing.json` exists and is updating: `curl http://localhost:8084/now-playing.json`
- Verify device received cast command in logs

### ESP32 won't connect to WiFi
- Check SSID and password in firmware
- Verify WiFi is 2.4GHz (ESP32 limitation)
- Check serial monitor for errors

### Art not loading
- Verify media server has artwork
- Check proxy/firewall isn't blocking image URLs
- For Plex: Verify token has permission to view artwork

## Documentation Map

- **FEATURE_SUMMARY.md** → Start here for overview
- **ARCHITECTURE_EMBY_ESP32.md** → Design and API details
- **IMPLEMENTATION_GUIDE.md** → How to integrate into cast.py
- **ESP32_SETUP.md** → Hardware and firmware setup
- **QUICK_REFERENCE.md** → This file (quick lookups)

## Getting Help

1. Check logs: `docker compose logs -f marquee`
2. Review QUICK_REFERENCE.md (this file)
3. Check ARCHITECTURE_EMBY_ESP32.md for API details
4. Check ESP32_SETUP.md for hardware issues
5. Check IMPLEMENTATION_GUIDE.md for integration questions
6. Review code comments in Python modules

## Common Tasks

### Switch from Plex to Emby
1. Get Emby API key from settings
2. Update `compose.yaml`: `BACKEND_TYPE: emby`, `BACKEND_HOST`, `BACKEND_TOKEN`
3. `docker compose up -d --build`

### Add ESP32 Display
1. Flash ESP32 with `esp32/marquee_display.ino`
2. Find ESP32 IP from serial monitor
3. Update `compose.yaml`: `DEVICE_TYPE: esp32`, `DEVICE_ADDRESS`
4. `docker compose up -d --build`

### Test New Backend Before Deploying
```python
python3 << 'EOF'
from cast.media_backends import create_backend
backend = create_backend("emby", "http://localhost:8096", "your-key")
print("Health:", backend.get_health())
print("Session:", backend.get_current_session(set()))
EOF
```

### Verify Device Connectivity
```bash
# Cast device
catt -d 192.168.1.50 info

# ESP32 device
curl http://192.168.1.100/status
```

## Performance Tips

- **Plex**: Keep server on same LAN, use dedicated network if possible
- **Emby**: Similar to Plex; verify API key has proper permissions
- **Cast**: Ensure Hub is powered and WiFi connected
- **ESP32**: Keep within WiFi range; 40MHz SPI frequency should be adequate
- **Polling**: Default 5s is balanced; don't go below 2s

## Version Info

- **Feature Branch**: `feature/emby-esp32-support`
- **Base Version**: Marquee 1.3.0+
- **Python**: 3.6+
- **ESP32 Firmware**: 1.0.0 (reference)
- **Dependencies**: None new (uses stdlib + existing `catt`)
