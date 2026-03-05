"""Optional notifications: macOS local, Slack webhook."""

from __future__ import annotations

import logging
from typing import Optional

log = logging.getLogger("tutor_feedback.automation")


def notify_macos(title: str, body: str, subtitle: Optional[str] = None) -> bool:
    """Send a local macOS notification. Returns True if sent."""
    try:
        import subprocess
        cmd = [
            "osascript", "-e",
            f'display notification "{body}" with title "{title}"'
            + (f' subtitle "{subtitle}"' if subtitle else ""),
        ]
        subprocess.run(cmd, capture_output=True, check=False, timeout=5)
        return True
    except Exception as e:
        log.debug("macOS notification failed: %s", e)
        return False


def notify_slack(
    webhook_url: str,
    text: str,
    username: Optional[str] = None,
    channel: Optional[str] = None,
) -> bool:
    """Post to Slack via incoming webhook. Returns True if sent."""
    try:
        import urllib.request
        import json as _json
        payload = {"text": text}
        if username:
            payload["username"] = username
        if channel:
            payload["channel"] = channel
        data = _json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            webhook_url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except Exception as e:
        log.warning("Slack notification failed: %s", e)
        return False
