"""Restricted shell tool for Jarvis.

- Allowlist command *binaries* (first token)
- Blocklist dangerous patterns
- Runs with a short timeout

This is intentionally conservative.
"""

from __future__ import annotations

import os
import shlex
import subprocess
from typing import Dict

import yaml

POLICIES_PATH = os.path.join(os.path.dirname(__file__), "..", "configs", "policies.yaml")


def _load_shell_policy() -> Dict:
    try:
        with open(POLICIES_PATH, "r") as f:
            cfg = yaml.safe_load(f) or {}
        return cfg.get("shell", {})
    except Exception:
        return {}


def _is_allowed(command: str, policy: Dict) -> (bool, str):
    cmd = (command or "").strip()
    if not cmd:
        return False, "command is empty"

    blocked = policy.get("blocked_patterns", []) or []
    for pat in blocked:
        if pat and pat in cmd:
            return False, f"blocked pattern detected: {pat}"

    try:
        parts = shlex.split(cmd)
    except Exception:
        return False, "failed to parse command"

    binary = parts[0] if parts else ""
    allowed = set(policy.get("allowed_commands", []) or [])
    if binary not in allowed:
        return False, f"'{binary}' is not in allowlist"

    return True, "ok"


def run(command: str, timeout_s: int = 8) -> Dict:
    policy = _load_shell_policy()
    if not policy.get("enabled", True):
        return {"success": False, "error": "shell tool is disabled by policy"}

    ok, reason = _is_allowed(command, policy)
    if not ok:
        return {"success": False, "error": reason}

    try:
        proc = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            cwd=os.getcwd(),
        )
        return {
            "success": proc.returncode == 0,
            "returncode": proc.returncode,
            "output": (proc.stdout or "")[:8000],
            "stderr": (proc.stderr or "")[:8000],
            "error": "" if proc.returncode == 0 else (proc.stderr or "command failed")[:4000],
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "error": f"command timed out after {timeout_s}s"}
    except Exception as e:
        return {"success": False, "error": str(e)}


TOOL_DEF = {
    "name": "shell",
    "description": "Run a restricted allowlisted shell command (safe mode).",
    "parameters": {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "Shell command to run (allowlisted binaries only)"},
        },
        "required": ["command"],
    },
}
