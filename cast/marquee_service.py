"""Marquee service orchestration layer.

Coordinates media backend (Plex/Emby) polling with device target (Cast/ESP32) control.
Handles lifecycle transitions: playing → casting, stopping → idle, etc.
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
from typing import Optional, Dict, Any, Set

from media_backends import create_backend, MediaBackend
from device_targets import create_device_target, DeviceTarget, GoogleCastTarget


class MarqueeService:
    """Marquee service: polls media server, manages device playback."""

    def __init__(
        self,
        backend_type: str,
        backend_host: str,
        backend_token: str,
        device_type: str,
        device_address: str,
        device_port: Optional[int] = None,
        poll_seconds: int = 5,
        output_dir: str = "/app/output",
        data_dir: str = "/config",
        page_url: str = "",
    ):
        """Initialize Marquee service.

        Args:
            backend_type: 'plex' or 'emby'
            backend_host: Media server URL
            backend_token: Auth token (X-Plex-Token or Emby API key)
            device_type: 'cast' or 'esp32'
            device_address: Device IP address
            device_port: Device port (optional, used for ESP32)
            poll_seconds: Polling interval
            output_dir: Directory for generated files (now-playing.json, art)
            data_dir: Directory for persisted settings
            page_url: URL of the card page (for casting)
        """
        self.backend: MediaBackend = create_backend(
            backend_type, backend_host, backend_token
        )
        self.device: DeviceTarget = create_device_target(
            device_type, device_address, device_port
        )
        self.poll_seconds = poll_seconds
        self.output_dir = output_dir
        self.data_dir = data_dir
        self.page_url = page_url
        self.json_path = os.path.join(output_dir, "now-playing.json")
        self.last_playing = None
        self.tick = 0

        os.makedirs(output_dir, exist_ok=True)
        os.makedirs(data_dir, exist_ok=True)

    def _atomic_write(self, path: str, data: str, mode: str = "w") -> None:
        """Write file atomically via temp file."""
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path))
        try:
            with os.fdopen(fd, mode) as f:
                f.write(data)
            os.replace(tmp, path)
            os.chmod(path, 0o644)
        except Exception:
            try:
                os.close(fd)
            except Exception:
                pass
            if os.path.exists(tmp):
                os.remove(tmp)
            raise

    def poll_session(self, allowed_users: Set[str]) -> Optional[Dict[str, Any]]:
        """Poll media backend for current session.

        Args:
            allowed_users: Set of usernames that trigger display (empty = all)

        Returns:
            Session dict or None if idle
        """
        try:
            return self.backend.get_current_session(allowed_users)
        except Exception as e:
            print(f"session poll failed: {e}", flush=True)
            return None

    def save_session_json(self, info: Optional[Dict[str, Any]]) -> None:
        """Write now-playing state to JSON file."""
        self._atomic_write(
            self.json_path,
            json.dumps(info or {"playing": False}),
        )

    def cast_to_device(self, info: Dict[str, Any]) -> None:
        """Cast the card page to the device.

        Args:
            info: Session info dict (used for logging)
        """
        if not self.page_url:
            print(
                "no page URL configured — cannot cast",
                flush=True,
            )
            return

        try:
            # For Cast devices, verify DashCast is active; for ESP32, just send
            if isinstance(self.device, GoogleCastTarget):
                if not self.device.dashcast_active():
                    print(
                        f"DashCast not active on {self.device.ip}; launching...",
                        flush=True,
                    )
            title = info.get("title", "unknown")
            print(f"playing {title} -> casting", flush=True)
            # Add cache-buster to card URL
            sep = "&" if "?" in self.page_url else "?"
            url_to_cast = f"{self.page_url}{sep}cb={int(time.time())}"
            self.device.cast_url(url_to_cast)
        except Exception as e:
            print(f"cast failed: {e}", flush=True)

    def release_device(self) -> None:
        """Stop playback and return device to idle."""
        try:
            print("idle -> releasing device", flush=True)
            self.device.stop()
        except Exception as e:
            print(f"release failed: {e}", flush=True)

    def run(self, allowed_users: Set[str]) -> None:
        """Main service loop: poll, update JSON, manage casting.

        Args:
            allowed_users: Set of Plex/Emby usernames that trigger marquee
        """
        print(
            f"Marquee service ready (backend: {self.backend.__class__.__name__}, "
            f"device: {self.device.__class__.__name__})",
            flush=True,
        )

        while True:
            try:
                # Poll for current session
                info = self.poll_session(allowed_users)
                self.save_session_json(info)
                playing = bool(info)

                # Transition check: entering or exiting playback
                # Or periodic reconciliation (every 6 polls = ~30s)
                if playing != self.last_playing or self.tick % 6 == 0:
                    if not self.device.is_available():
                        if playing and playing != self.last_playing:
                            print(
                                f"device at {self.device.get_info().get('ip')} unreachable",
                                flush=True,
                            )
                    else:
                        if playing and not self.last_playing:
                            # Transition: idle → playing
                            self.cast_to_device(info)
                        elif not playing and self.last_playing:
                            # Transition: playing → idle
                            self.release_device()

                self.last_playing = playing
                self.tick += 1

            except Exception as e:
                print(f"service loop error: {e}", flush=True)

            time.sleep(self.poll_seconds)

    def get_status(self) -> Dict[str, Any]:
        """Get current service status."""
        return {
            "backend": {
                "type": self.backend.__class__.__name__,
                "healthy": self.backend.get_health(),
            },
            "device": {
                "type": self.device.__class__.__name__,
                **self.device.get_info(),
                "available": self.device.is_available(),
            },
            "last_session": self.last_playing,
            "tick": self.tick,
        }
