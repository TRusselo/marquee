# Advanced: Multiple Displays & Coordination

Guide for managing multiple ESPHome displays with Marquee.

## Scenarios

### Scenario 1: Same Display, Multiple Rooms

You have one Marquee server but displays in different rooms (living room, bedroom, kitchen).

```
Marquee Server (1)
    ↓
    ├→ ESPHome Display 1 (Living Room)
    ├→ ESPHome Display 2 (Bedroom)
    └→ ESPHome Display 3 (Kitchen)
    
All poll /api/now-playing.json independently
```

**Setup:**

Each ESPHome device has its own config but same Marquee URL:

```yaml
# living_room_display.yaml
esphome:
  name: living-room-display

text_sensor:
  - platform: http_request
    resource: http://192.168.1.10:8084/api/now-playing.json
    scan_interval: 5s

# bedroom_display.yaml
esphome:
  name: bedroom-display

text_sensor:
  - platform: http_request
    resource: http://192.168.1.10:8084/api/now-playing.json  # Same URL
    scan_interval: 5s

# kitchen_display.yaml
esphome:
  name: kitchen-display

text_sensor:
  - platform: http_request
    resource: http://192.168.1.10:8084/api/now-playing.json  # Same URL
    scan_interval: 5s
```

**Result:** All three displays show the same Marquee card when content is playing.

**No Home Assistant needed.** Each device independently fetches and displays.

---

### Scenario 2: Different Strategies Per Device

Different displays have different behavior:

- **Living room**: Full-screen Marquee on play
- **Bedroom**: Persistent sidebar widget
- **Kitchen**: Text-only mode (no images)

```yaml
# living_room_display.yaml - Full screen strategy
esphome:
  name: living-room-display

display:
  - platform: ili9341
    pages:
      - id: marquee_page
        lambda: |-
          # Full-screen rendering
      - id: idle_page
        lambda: |-
          # Idle screen

text_sensor:
  - platform: http_request
    id: marquee_json
    on_value:
      then:
        - lambda: |-
            auto root = json::parse_json(x);
            if (root["playing"].as<bool>()) {
              id(my_display).show_page(id(marquee_page));
            } else {
              id(my_display).show_page(id(idle_page));
            }
```

```yaml
# bedroom_display.yaml - Widget strategy
esphome:
  name: bedroom-display

display:
  - platform: ili9341
    pages:
      - id: main_page
        lambda: |-
          // Draw dashboard + Marquee sidebar

text_sensor:
  - platform: http_request
    id: marquee_json
    on_value:
      then:
        - component.update: my_display
```

```yaml
# kitchen_display.yaml - Text-only strategy
esphome:
  name: kitchen-display

display:
  - platform: ssd1306_i2c  # Small OLED, text-only
    id: oled_display

text_sensor:
  - platform: http_request
    id: marquee_json
    on_value:
      then:
        - lambda: |-
            auto root = json::parse_json(x);
            // Text-only rendering
```

**Result:** Each room's display behaves differently, all from one Marquee server.

---

### Scenario 3: With Home Assistant Orchestration

Use HA to control displays based on context:

```yaml
# automations.yaml

# Living room: Always show Marquee on play
- alias: "Living Room Marquee: Show"
  trigger:
    - platform: state
      entity_id: media_player.plex_living_room
      to: "playing"
  action:
    - service: esphome.living_room_display_show_marquee

# Bedroom: Only show if home (don't disturb when away)
- alias: "Bedroom Marquee: Show if Home"
  trigger:
    - platform: state
      entity_id: media_player.plex_bedroom
      to: "playing"
  condition:
    - condition: state
      entity_id: group.all_people
      state: "home"
  action:
    - service: esphome.bedroom_display_show_marquee

# Kitchen: Show only during certain hours
- alias: "Kitchen Marquee: Show (daytime)"
  trigger:
    - platform: state
      entity_id: media_player.plex_kitchen
      to: "playing"
  condition:
    - condition: time
      after: "09:00:00"
      before: "22:00:00"
  action:
    - service: esphome.kitchen_display_show_marquee
```

---

## Coordination: Synchronized vs. Independent

### Independent Polling (Simplest)

Each device polls Marquee independently:

```
Living Room Display  ──┐
                       │
Bedroom Display ──────┼→ Marquee API
                       │
Kitchen Display ───────┘

Each polls every 5 seconds independently
```

**Pros:**
- Simple, no coordination needed
- Resilient (one display failure doesn't affect others)
- Works without Home Assistant

**Cons:**
- Multiple requests to Marquee server (usually fine)
- Small delays between updates (a few seconds)

**Best for:** Most use cases (3-5 devices)

---

### Synchronized via MQTT (Advanced)

Use MQTT to coordinate:

```
┌─────────────────────────────────────────┐
│  Home Assistant + Mosquitto MQTT Broker │
└─────────────────────────────────────────┘
          ↑      ↑      ↑
          │      │      │
Living Room  Bedroom  Kitchen
Display      Display  Display

Each device:
1. Polls Marquee
2. Publishes state to MQTT
3. Subscribes to commands
```

**ESPHome device publishes:**

```yaml
text_sensor:
  - platform: http_request
    id: marquee_json
    on_value:
      then:
        - mqtt.publish:
            topic: "marquee/{{ device_name }}/state"
            payload: !lambda 'return id(marquee_json).state;'
```

**HA subscribes and broadcasts:**

```yaml
mqtt:
  sensor:
    - name: "Living Room Marquee"
      state_topic: "marquee/living_room/state"
      json_attributes: true

automation:
  - alias: "Broadcast Marquee to All Displays"
    trigger:
      - platform: mqtt
        topic: "marquee/living_room/state"
    action:
      - service: mqtt.publish
        data:
          topic: "marquee/broadcast/state"
          payload: "{{ trigger.payload }}"
```

**Pros:**
- True synchronization
- Can broadcast state to all devices
- Flexible, allows filtering

**Cons:**
- Requires MQTT broker
- More complex setup
- Adds a dependency

**Best for:** 5+ devices or complex orchestration

---

## Multi-Room Automations (with Home Assistant)

### Example 1: Show Marquee in Specific Room

```yaml
# automations.yaml

- alias: "Living Room Playing"
  trigger:
    - platform: state
      entity_id: media_player.plex_living_room
      to: "playing"
  action:
    - service: esphome.living_room_display_show_marquee

- alias: "Bedroom Playing"
  trigger:
    - platform: state
      entity_id: media_player.plex_bedroom
      to: "playing"
  action:
    - service: esphome.bedroom_display_show_marquee

- alias: "Kitchen Playing"
  trigger:
    - platform: state
      entity_id: media_player.plex_kitchen
      to: "playing"
  action:
    - service: esphome.kitchen_display_show_marquee
```

---

### Example 2: Show Marquee in "Active" Room

Determine which room is being used, show Marquee there:

```yaml
# automations.yaml

- alias: "Show Marquee Where Content is Playing"
  trigger:
    - platform: state
      entity_id: media_player.plex_living_room
      to: "playing"
    - platform: state
      entity_id: media_player.plex_bedroom
      to: "playing"
  action:
    - choose:
        # Living room playing
        - conditions:
            - condition: state
              entity_id: media_player.plex_living_room
              state: "playing"
          sequence:
            - service: esphome.living_room_display_show_marquee
            - service: esphome.bedroom_display_hide_marquee  # Hide others
            - service: esphome.kitchen_display_hide_marquee
        
        # Bedroom playing
        - conditions:
            - condition: state
              entity_id: media_player.plex_bedroom
              state: "playing"
          sequence:
            - service: esphome.bedroom_display_show_marquee
            - service: esphome.living_room_display_hide_marquee  # Hide others
            - service: esphome.kitchen_display_hide_marquee
```

---

### Example 3: Show Marquee on ALL Displays

Some use case requires showing on multiple displays simultaneously:

```yaml
- alias: "Movie Night: Show Marquee Everywhere"
  trigger:
    - platform: state
      entity_id: input_boolean.movie_night
      to: "on"
  action:
    - service: esphome.living_room_display_show_marquee
    - service: esphome.bedroom_display_show_marquee
    - service: esphome.kitchen_display_show_marquee
```

---

## Scaling: 10+ Displays

### Use a Template

For many displays, create a template:

```yaml
# scripts.yaml

script:
  show_marquee_everywhere:
    sequence:
      - repeat:
          count: "{{ devices | length }}"
          sequence:
            - service: esphome."{{ devices[repeat.index - 1] }}_display_show_marquee"

  hide_marquee_everywhere:
    sequence:
      - repeat:
          count: "{{ devices | length }}"
          sequence:
            - service: esphome."{{ devices[repeat.index - 1] }}_display_hide_marquee"
```

### Use MQTT (Recommended)

With 10+ devices, MQTT becomes the right choice:

```yaml
# All devices subscribe to single topic
mqtt:
  - topic: "marquee/command"
    payload: "show"
    service: esphome.marquee_show_all

# Single command triggers all
- alias: "Show Marquee on All"
  action:
    - service: mqtt.publish
      data:
        topic: "marquee/command"
        payload: "show"
```

---

## Troubleshooting Multi-Display Setup

### One display doesn't update

**Check:**
1. Device is online: `ping 192.168.1.101`
2. WiFi signal is strong
3. Device can reach Marquee server: `curl http://192.168.1.10:8084/api/now-playing.json` (from device's network)
4. GPIO pins are correct in config

### Displays get out of sync

**Cause:** Poll intervals differ between devices  
**Fix:** Set all to same `scan_interval` (e.g., 5s)

### MQTT not working

**Check:**
1. Mosquitto add-on is running in HA
2. Credentials are correct
3. ESPHome device connected: `ESPHome → Living Room Display → Logs`
4. Topic names match between publish/subscribe

---

## Best Practices

✅ **Do:**
- Use consistent naming (e.g., `marquee-display-1`, `marquee-display-2`)
- Set same poll interval on all devices (5s is good)
- Use HA templates to reduce automation boilerplate
- Monitor HA logs: `Settings → System → Logs`

❌ **Don't:**
- Poll faster than 3s (wastes bandwidth)
- Run 20+ devices without MQTT (use MQTT for >10 devices)
- Mix different display types without careful lambda code (may cause crashes)
- Hardcode IPs in automations (use entity_id instead)

---

## Performance Notes

### Network Traffic

With N displays polling every 5 seconds:
- Each poll: ~2KB HTTP request + response
- Total: N × 2KB / 5s = 0.4NK/s bandwidth
- Example: 10 devices = 4KB/s (negligible)

### Marquee Server Load

- Each poll requires one backend query (Plex/Emby)
- With 10 devices: 10 queries/5s = 2 queries/second
- Most servers handle 10-20 queries/second easily

**Recommendation:** If you have 20+ devices, consider caching or MQTT broadcast.

---

## Next Steps

✅ Multiple displays set up and polling  
✅ Each displays its own rendering  
✅ (Optional) Automations coordinating behavior  

🎯 **Next:**
- Monitor performance
- Adjust poll intervals if needed
- Add HA automations for intelligence
- Scale to more devices as needed
