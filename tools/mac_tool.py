"""macOS control tool (best-effort).

Runs only on macOS; elsewhere returns a helpful error.
"""

from __future__ import annotations

import os
import platform
import subprocess
from typing import Dict

import yaml

POLICIES_PATH = os.path.join(os.path.dirname(__file__), "..", "configs", "policies.yaml")


def _load_policy() -> Dict:
    try:
        with open(POLICIES_PATH, "r") as f:
            cfg = yaml.safe_load(f) or {}
        return cfg.get("mac", {}) or {}
    except Exception:
        return {}


def _ensure_macos() -> bool:
    return platform.system().lower() == "darwin"


def _osascript(script: str) -> subprocess.CompletedProcess:
    return subprocess.run(["osascript", "-e", script], capture_output=True, text=True)


def run(action: str, **kwargs) -> Dict:
    policy = _load_policy()
    if not policy.get("enabled", True):
        return {"success": False, "error": "mac tool is disabled by policy"}

    action = (action or "").strip()
    allowed = set(policy.get("allowed_actions", []) or [])
    # Normalize: tool exposes action names without prefix sometimes
    if action in ("open_app", "open_url", "notify", "screenshot") and action not in allowed:
        return {"success": False, "error": f"action '{action}' not allowed by policy"}

    if not _ensure_macos():
        return {"success": False, "error": "mac_control is only available on macOS"}

    try:
        if action == "open_app":
            app = kwargs.get("app") or kwargs.get("name")
            if not app:
                return {"success": False, "error": "app is required"}
            proc = subprocess.run(["open", "-a", app], capture_output=True, text=True)
            return {"success": proc.returncode == 0, "output": proc.stdout.strip(), "error": proc.stderr.strip()}

        if action == "open_url":
            url = kwargs.get("url")
            if not url:
                return {"success": False, "error": "url is required"}
            proc = subprocess.run(["open", url], capture_output=True, text=True)
            return {"success": proc.returncode == 0, "output": proc.stdout.strip(), "error": proc.stderr.strip()}

        if action == "notify":
            title = kwargs.get("title", "Jarvis")
            message = kwargs.get("message", "")
            if not message:
                return {"success": False, "error": "message is required"}
            script = f'display notification {message!r} with title {title!r}'
            proc = _osascript(script)
            return {"success": proc.returncode == 0, "output": proc.stdout.strip(), "error": proc.stderr.strip()}

        if action == "screenshot":
            path = kwargs.get("path") or os.path.join(os.path.expanduser("~"), "Desktop", "jarvis_screenshot.png")
            proc = subprocess.run(["screencapture", "-x", path], capture_output=True, text=True)
            return {"success": proc.returncode == 0, "output": path if proc.returncode == 0 else "", "error": proc.stderr.strip()}

        return {"success": False, "error": f"Unknown action: {action}"}

    except Exception as e:
        return {"success": False, "error": str(e)}


TOOL_DEF = {
    "name": "mac",
    "description": "Control macOS (open apps/URLs, notifications, screenshots).",
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["open_app", "open_url", "notify", "screenshot"], "description": "Action"},
            "app": {"type": "string", "description": "Application name for open_app"},
            "url": {"type": "string", "description": "URL for open_url"},
            "title": {"type": "string", "description": "Notification title"},
            "message": {"type": "string", "description": "Notification message"},
            "path": {"type": "string", "description": "Screenshot output path"},
        },
        "required": ["action"],
    },
}
