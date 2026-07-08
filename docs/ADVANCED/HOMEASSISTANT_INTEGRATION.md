# Home Assistant Integration (Advanced Setup)

**Advanced option for users who already have Home Assistant.**

If you have Home Assistant running with Plex/Emby, you can use HA as the orchestrator to trigger Marquee displays intelligently. This is optional — ESPHome + Marquee works fine standalone.

## Overview

### Without Home Assistant
```
ESPHome Device
    ↓ (polls every 5s)
Marquee API (/api/now-playing.json)
    ↓
Display updates
```

**Pro**: Simple, no dependencies  
**Con**: Display always updates on a schedule, can't trigger on exact playback events

---

### With Home Assistant
```
Plex/Emby Server
    ↓
Home Assistant (media_player.plex_*, media_player.emby_*)
    ↓ (listens for state changes)
    ├→ Automation: "Play started" → trigger display
    ├→ Automation: "Play paused" → dim display
    ├→ Automation: "Play stopped" → return to dashboard
    └→ Automation: "Away mode" → turn off display
        ↓
    ESPHome Display
        ↓
    User sees intelligent behavior
```

**Pro**: Responsive, intelligent, integrates with other HA automations  
**Con**: More setup, requires Home Assistant

---

## When to Use Home Assistant Integration

✅ **Use HA if you:**
- Already have Home Assistant running
- Want responsive display behavior (instant play/pause detection)
- Have multiple ESPHome displays
- Want to integrate with other HA automations (lights, notifications, etc.)
- Like YAML configuration

❌ **Stick with ESPHome-only if you:**
- Don't have Home Assistant
- Want simplicity (fewer moving parts)
- Don't need responsive behavior (5s polling is fine)
- Prefer "set and forget" config

---

## Prerequisites

- ✅ Home Assistant (running and accessible)
- ✅ Plex or Emby integration in HA
- ✅ ESPHome device(s) added to HA
- ✅ Marquee server running
- ✅ All devices on same local network

---

## Home Assistant Configuration

### Step 1: Verify Media Player Entities

In Home Assistant, check that you have media player entities:

```yaml
# Configuration -> Entities
# Look for:
media_player.plex_living_room
media_player.emby_bedroom
# or similar
```

If you don't have these, install:
- [Plex integration](https://www.home-assistant.io/integrations/plex/)
- [Emby integration](https://www.home-assistant.io/integrations/emby/)

### Step 2: Verify ESPHome Device

Ensure your ESPHome display is added to Home Assistant:

```yaml
# Configuration -> Integrations -> ESPHome
# Should show your marquee-display device
```

If not, add it:
1. Go to **Settings → Devices & Services → Create Integration**
2. Search for "ESPHome"
3. Enter your ESP32 IP address: `192.168.1.100`

### Step 3: Add Marquee REST Command

Edit `configuration.yaml` or create `rest_command.yaml`:

```yaml
# configuration.yaml
rest_command:
  marquee_display_url:
    url: "http://192.168.1.10:8084/api/now-playing.json"
    method: GET
```

This allows HA to fetch Marquee data directly.

### Step 4: Create Helper for Marquee State

Create a template sensor that tracks whether Marquee should be displayed:

```yaml
# configuration.yaml
template:
  - sensor:
      - name: "Plex Playing"
        unique_id: plex_playing
        unit_of_measurement: ""
        state: >
          {% if states('media_player.plex_living_room') == 'playing' %}
            true
          {% else %}
            false
          {% endif %}
```

---

## Basic Automation: Play Started

### Scenario 1: Show Marquee on Play

When someone starts playing content, immediately show the Marquee card on the display.

**UI Method** (Easier):

1. Go to **Settings → Automations & Scenes → Create Automation**
2. Name: "Show Marquee on Play"
3. **Trigger**:
   - Trigger type: "State"
   - Entity: `media_player.plex_living_room`
   - To: `playing`
4. **Action**:
   - Action type: "Call service"
   - Service: `esphome.marquee_display_show_marquee` (or your device name)
5. Click **Create Automation**

**YAML Method** (More control):

```yaml
# automations.yaml
- alias: "Show Marquee on Play"
  trigger:
    - platform: state
      entity_id: media_player.plex_living_room
      to: "playing"
  action:
    - service: esphome.marquee_display_show_marquee
      data:
        card_url: "http://192.168.1.10:8084/image"
```

---

### Scenario 2: Hide Marquee on Stop

When playback stops, return to dashboard/idle screen.

```yaml
- alias: "Hide Marquee on Stop"
  trigger:
    - platform: state
      entity_id: media_player.plex_living_room
      to:
        - "paused"
        - "idle"
        - "off"
  action:
    - service: esphome.marquee_display_hide_marquee
```

---

### Scenario 3: Dim on Pause

Lower brightness when content is paused.

```yaml
- alias: "Dim Display on Pause"
  trigger:
    - platform: state
      entity_id: media_player.plex_living_room
      to: "paused"
  action:
    - service: light.turn_on
      target:
        entity_id: light.display_brightness  # From ESPHome
      data:
        brightness_pct: 30
```

---

## Advanced: Multiple Displays

### Scenario: Different Rooms

Control multiple ESPHome displays independently:

```yaml
# Living room: full-screen Marquee on play
- alias: "Living Room: Show Marquee on Play"
  trigger:
    - platform: state
      entity_id: media_player.plex_living_room
      to: "playing"
  action:
    - service: esphome.living_room_display_show_marquee

# Bedroom: sidebar widget (persistent)
- alias: "Bedroom: Show Marquee Widget"
  trigger:
    - platform: time_pattern
      minutes: "/5"  # Every 5 minutes
  action:
    - service: rest_command.fetch_marquee
```

---

## Integration with Other Automations

### Scenario: Turn Off Display When Away

```yaml
- alias: "Turn Off Display When Away"
  trigger:
    - platform: state
      entity_id: group.all_people
      to: "not_home"
  action:
    - service: light.turn_off
      target:
        entity_id: light.display_brightness
```

### Scenario: Notify When Content Starts

```yaml
- alias: "Notify on Plex Play"
  trigger:
    - platform: state
      entity_id: media_player.plex_living_room
      to: "playing"
  action:
    - service: notify.mobile_app_phone
      data:
        message: "Content started on display"
```

### Scenario: Display Marquee When Home

```yaml
- alias: "Show Marquee When Home"
  trigger:
    - platform: state
      entity_id: group.all_people
      to: "home"
  action:
    - service: light.turn_on
      target:
        entity_id: light.display_brightness
      data:
        brightness_pct: 100
```

---

## MQTT Integration (Multi-Device Coordination)

### Setup MQTT Broker

If you want to coordinate multiple ESPHome displays or other devices:

1. Install [Mosquitto Add-on](https://github.com/home-assistant/addons/tree/master/mosquitto) in HA
2. Or use external MQTT broker (e.g., `test.mosquitto.org`)

### Configure ESPHome to Use MQTT

Edit your ESPHome device config:

```yaml
# esphome config
mqtt:
  broker: 192.168.1.10  # Your HA IP
  username: mqtt_user
  password: mqtt_password
  discovery: true

# Publish Marquee state
text_sensor:
  - platform: http_request
    id: marquee_json
    resource: http://192.168.1.10:8084/api/now-playing.json
    scan_interval: 5s
    on_value:
      then:
        - mqtt.publish:
            topic: "marquee/now-playing"
            payload: !lambda 'return id(marquee_json).state;'
```

### Subscribe in Home Assistant

```yaml
# configuration.yaml
mqtt:
  sensor:
    - name: "Marquee Now Playing"
      state_topic: "marquee/now-playing"
      value_template: "{{ value_json.title }}"
      json_attributes_topic: "marquee/now-playing"
```

Now you can use the MQTT data in automations:

```yaml
- alias: "Display Marquee from MQTT"
  trigger:
    - platform: mqtt
      topic: "marquee/now-playing"
  action:
    - service: esphome.marquee_display_show_marquee
      data:
        card_url: "http://192.168.1.10:8084/image"
```

---

## Home Assistant Dashboard Card

### Display Marquee Control on HA Dashboard

```yaml
# Create a card to show/control display
type: custom:button-card
entity: media_player.plex_living_room
name: Marquee Display
style:
  card:
    - height: 200px

# Or simpler, using built-in card:
type: entities
entities:
  - light.display_brightness
  - media_player.plex_living_room
  - button.marquee_show
  - button.marquee_hide
```

### Add Control Buttons

Create template buttons in HA:

```yaml
# configuration.yaml
button:
  - platform: template
    marquee_show:
      friendly_name: "Show Marquee"
      press_action:
        service: esphome.marquee_display_show_marquee
        data:
          card_url: "http://192.168.1.10:8084/image"
  
  - platform: template
    marquee_hide:
      friendly_name: "Hide Marquee"
      press_action:
        service: esphome.marquee_display_hide_marquee
```

---

## Troubleshooting

### Automation doesn't trigger

**Check:**
1. Entity name is correct: `Developer Tools → States → Search for "media_player"`
2. Automation is enabled: `Settings → Automations → [Check toggle]`
3. Trigger condition is firing: Add a persistent notification action

```yaml
- alias: "Debug: Show Marquee on Play"
  trigger:
    - platform: state
      entity_id: media_player.plex_living_room
      to: "playing"
  action:
    - service: persistent_notification.create
      data:
        message: "Plex is playing!"
```

### ESPHome service not found

**Check:**
1. Device is added to HA: `Settings → Devices & Services → ESPHome`
2. Device name matches: Look in `Developer Tools → Services → esphome.marquee_display_*`
3. Device is online: Should show "Connected" in ESPHome integration

### Can't reach Marquee API

**Check:**
1. Marquee server URL is correct
2. Marquee is running: `curl http://192.168.1.10:8084/api/now-playing.json`
3. Firewall isn't blocking port 8084
4. All devices on same network

---

## Example: Complete Setup

Here's a complete Home Assistant setup with Plex + Marquee + ESPHome:

```yaml
# configuration.yaml

# MQTT (optional, for multi-device)
mqtt:
  broker: 192.168.1.10

# REST commands
rest_command:
  marquee_api:
    url: "http://192.168.1.10:8084/api/now-playing.json"
    method: GET

# Template sensors
template:
  - sensor:
      - name: "Marquee Now Playing"
        unique_id: marquee_now_playing
        state: >
          {% set plex = states('media_player.plex_living_room') %}
          {% if plex == 'playing' %}
            PLAYING
          {% else %}
            IDLE
          {% endif %}

# Automations
automation: !include automations.yaml
```

```yaml
# automations.yaml

# Show Marquee when content plays
- alias: "Marquee: Show on Play"
  trigger:
    - platform: state
      entity_id: media_player.plex_living_room
      to: "playing"
  action:
    - service: esphome.living_room_display_show_marquee

# Hide when stopped
- alias: "Marquee: Hide on Stop"
  trigger:
    - platform: state
      entity_id: media_player.plex_living_room
      to: ["paused", "idle", "off"]
  action:
    - service: esphome.living_room_display_hide_marquee

# Dim on pause
- alias: "Marquee: Dim on Pause"
  trigger:
    - platform: state
      entity_id: media_player.plex_living_room
      to: "paused"
  action:
    - service: light.turn_on
      target:
        entity_id: light.living_room_display_brightness
      data:
        brightness_pct: 30

# Turn off when away
- alias: "Marquee: Off When Away"
  trigger:
    - platform: state
      entity_id: group.all_people
      to: "not_home"
  action:
    - service: light.turn_off
      target:
        entity_id: light.living_room_display_brightness
```

---

## Comparison: ESPHome-Only vs. HA Integration

| Feature | ESPHome-Only | With HA |
|---------|-------------|--------|
| Setup complexity | Low | Medium |
| Response time | ~5s (poll interval) | Instant (event-based) |
| Multi-device | Easy | Easier |
| Integration with HA | No | Yes |
| Automations | Limited | Full HA power |
| Number of moving parts | 2 | 3-4 |
| "Set and forget" | Yes | More config |
| Requires HA | No | Yes |

---

## Next Steps

✅ ESPHome device is polling Marquee  
✅ HA sees your media player and display  
✅ Automations trigger based on playback state  

🎯 **Optional:**
- Add MQTT for multi-device coordination
- Create HA dashboard cards for manual control
- Integrate with other HA automations (lights, notifications)
- Set up away/home automations

---

## Resources

- [Home Assistant Plex Integration](https://www.home-assistant.io/integrations/plex/)
- [Home Assistant Emby Integration](https://www.home-assistant.io/integrations/emby/)
- [ESPHome Home Assistant Integration](https://esphome.io/components/api.html)
- [HA Automations Documentation](https://www.home-assistant.io/docs/automation/)
- [MQTT in Home Assistant](https://www.home-assistant.io/integrations/mqtt/)

---

**Remember**: This is **optional**. ESPHome + Marquee works great standalone without Home Assistant. Use HA integration only if you want the added intelligence and control. 🏠
