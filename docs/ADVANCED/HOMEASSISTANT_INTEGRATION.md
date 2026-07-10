# Home Assistant Integration (Advanced Setup)

> ### ⚠️ Test branch — never run on hardware
>
> This document describes work in progress on `feature/emby-esp32-support`, a
> fork of [Jamisonfitz/marquee](https://github.com/Jamisonfitz/marquee).
> **No ESP32, no display panel, and no Cast device has ever run this code.**
> The wiring, the YAML, and the firmware here are untested proposals: pin
> assignments, timings, and library calls may simply be wrong.
>
> Nothing below should be trusted until you have verified it yourself. Expect
> to debug. Please report what you find.

**Optional. For users who already run Home Assistant.** ESPHome + Marquee works
fine on its own — Home Assistant just adds *intelligent extras* on top, like
dimming the display while a movie plays or turning it off when you leave.

> **Important — what HA does and does not do here.**
> Home Assistant does **not** tell the display to "show the card." The ESPHome
> display decides that itself by polling Marquee's `/api/now-playing.json` and
> switching to the marquee page when something is playing (see
> [../ESPHOME/ESPHOME_CONFIG.md](../ESPHOME/ESPHOME_CONFIG.md), the "interrupt"
> example). HA's role is **orthogonal automation** — brightness, power, presence,
> notifications — using entities the ESPHome device already exposes. There is no
> custom `esphome.*_show_marquee` service; don't look for one.

## How the pieces fit

```
Plex / Emby ──► Marquee ──► /api/now-playing.json
                                   ▲
                                   │ polls every ~5s, switches page itself
                          ESPHome display  ◄────────────── Home Assistant
                          (light.display_brightness,        (automations:
                           marquee/idle pages)               dim on play, off when away, …)
```

- **The display showing/hiding the card:** handled by ESPHome polling, not HA.
- **Everything smart around it:** handled by HA automations on the display's
  entities (brightness light, etc.) and the `media_player` state HA already has.

## Prerequisites

- Home Assistant running and reachable
- Plex or Emby integration active in HA (gives you `media_player.*` entities)
- An ESPHome display added to HA, built from
  [../ESPHOME/ESPHOME_CONFIG.md](../ESPHOME/ESPHOME_CONFIG.md) — specifically
  including the `light: monochromatic` **brightness** entity from that guide
- Marquee running and reachable at `http://<marquee-ip>:8084`

Find your exact entity IDs under **Developer Tools → States**. Below we use
`media_player.plex_living_room` and `light.display_brightness` as placeholders —
yours will reflect your device names.

## The flagship automation: dim the display while playing

You don't want a bright screen competing with the movie. So **dim on play,
restore when it stops.**

```yaml
# automations.yaml
- alias: "Marquee: dim display while playing"
  trigger:
    - platform: state
      entity_id: media_player.plex_living_room
      to: "playing"
  action:
    - service: light.turn_on
      target:
        entity_id: light.display_brightness
      data:
        brightness_pct: 15        # low, non-distracting

- alias: "Marquee: restore brightness when not playing"
  trigger:
    - platform: state
      entity_id: media_player.plex_living_room
      to: ["paused", "idle", "off"]
  action:
    - service: light.turn_on
      target:
        entity_id: light.display_brightness
      data:
        brightness_pct: 100
```

That's the whole idea, and it works because `light.display_brightness` is a real
entity your ESPHome config publishes. Everything below is variations on this.

## Turn the display off when you leave

```yaml
- alias: "Marquee: off when away"
  trigger:
    - platform: state
      entity_id: group.all_people   # or a person/zone helper
      to: "not_home"
  action:
    - service: light.turn_off
      target:
        entity_id: light.display_brightness

- alias: "Marquee: on when home"
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

## Optional: notify when something starts

```yaml
- alias: "Marquee: notify on play"
  trigger:
    - platform: state
      entity_id: media_player.plex_living_room
      to: "playing"
  action:
    - service: notify.mobile_app_phone
      data:
        message: >
          Now playing: {{ state_attr('media_player.plex_living_room',
          'media_title') }}
```

Note this reads `media_title` from the **HA media_player** — HA already knows
what's playing, so you don't need to fetch Marquee's JSON for this.

## Multiple displays

Each display is just its own brightness entity. Repeat the dim-on-play
automation per room, targeting that room's light and (optionally) that room's
player:

```yaml
- alias: "Living room: dim on play"
  trigger:
    - platform: state
      entity_id: media_player.plex_living_room
      to: "playing"
  action:
    - service: light.turn_on
      target: { entity_id: light.living_room_display_brightness }
      data: { brightness_pct: 15 }

- alias: "Bedroom: dim on play"
  trigger:
    - platform: state
      entity_id: media_player.plex_bedroom
      to: "playing"
  action:
    - service: light.turn_on
      target: { entity_id: light.bedroom_display_brightness }
      data: { brightness_pct: 10 }
```

No coordination server needed — each ESPHome device independently polls Marquee
and each automation independently manages its display. See
[MULTIPLE_DISPLAYS.md](MULTIPLE_DISPLAYS.md) for more on scaling out.

## If you really want HA to read Marquee's JSON

Usually unnecessary (HA's `media_player` already has play state, title, etc.).
But if you want the *card's exact fields* in HA, use a **REST sensor** — not a
`rest_command` (a `rest_command` fires a request and discards the response, so it
can't feed automations):

```yaml
# configuration.yaml
sensor:
  - platform: rest
    name: "Marquee Now Playing"
    resource: "http://192.168.1.10:8084/api/now-playing.json"
    scan_interval: 10
    value_template: "{{ value_json.playing }}"
    json_attributes:
      - title
      - year
      - progress
```

`/api/now-playing.json` is a real, CORS-enabled endpoint that returns the live
card state (or `{"playing": false}` when idle).

## Optional: event-driven page switch (instead of polling)

Polling (the default) is simplest and what the ESPHome guide sets up. If you
want *instant* page switching driven by HA, define your own service **in the
ESPHome device YAML** that switches the display page, then call it from an
automation:

```yaml
# In the ESPHome device config (not Marquee, not HA):
api:
  services:
    - service: show_marquee
      then:
        - display.page.show: marquee_page
    - service: hide_marquee
      then:
        - display.page.show: idle_page
```

```yaml
# HA automation can then call it (service name = esphome.<device>_show_marquee):
- alias: "Marquee: show on play (event-driven)"
  trigger:
    - platform: state
      entity_id: media_player.plex_living_room
      to: "playing"
  action:
    - service: esphome.marquee_display_show_marquee
```

These services only exist if **you add them** to your ESPHome config as shown —
they are not built in.

## MQTT (only if you already run a broker)

For large fan-outs you can bridge state over MQTT. Two honest caveats:

- **Use your own broker** (e.g. the Mosquitto add-on). Do not route home media
  state through a public broker.
- **Don't publish the whole JSON from an ESPHome `text_sensor`** — ESPHome text
  values are capped around 255 bytes and the card JSON is larger, so it would be
  truncated. Publish a small boolean/topic instead (e.g. `marquee/playing` =
  `on`/`off`) driven by an HA automation, and let subscribers react to that.

```yaml
# HA automation publishing a compact play/stop signal
- alias: "Marquee: publish play state to MQTT"
  trigger:
    - platform: state
      entity_id: media_player.plex_living_room
  action:
    - service: mqtt.publish
      data:
        topic: "marquee/playing"
        payload: >
          {{ 'on' if is_state('media_player.plex_living_room', 'playing')
             else 'off' }}
```

## Troubleshooting

**Dim-on-play does nothing**
- Confirm `light.display_brightness` exists: **Developer Tools → States**. If
  not, your ESPHome config is missing the `light: monochromatic` block from
  [../ESPHOME/ESPHOME_CONFIG.md](../ESPHOME/ESPHOME_CONFIG.md).
- Confirm the trigger fires: temporarily add a
  `persistent_notification.create` action.
- Check the `media_player` entity name and that it actually reports `playing`.

**Card never appears on the display**
- That's ESPHome, not HA. Verify the device is polling and switching pages:
  `curl http://<marquee-ip>:8084/api/now-playing.json` should return
  `"playing": true` during playback. Then check the ESPHome page-switch lambda.

**Can't reach the Marquee API**
- `curl http://<marquee-ip>:8084/api/now-playing.json`
- Same LAN/VLAN; port 8084 not firewalled.

## ESPHome-only vs. HA integration

| | ESPHome-only | With Home Assistant |
|---|---|---|
| Show/hide card | ESPHome polls, switches page | Same (ESPHome still does it) |
| Dim while playing | Manual/none | Automatic (dim-on-play) |
| Off when away | No | Yes (presence) |
| Notifications | No | Yes |
| Moving parts | 2 | 3 |
| Requires HA | No | Yes |

## Resources

- [Home Assistant Plex integration](https://www.home-assistant.io/integrations/plex/)
- [Home Assistant Emby integration](https://www.home-assistant.io/integrations/emby/)
- [ESPHome ↔ Home Assistant API](https://esphome.io/components/api.html)
- [HA automations](https://www.home-assistant.io/docs/automation/)
- Marquee ESPHome setup: [../ESPHOME/ESPHOME_CONFIG.md](../ESPHOME/ESPHOME_CONFIG.md)

**Remember:** this is optional. The display shows the card on its own by polling
Marquee; Home Assistant just makes it behave intelligently around that.
