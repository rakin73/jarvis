"""Saviynt helper tool.

Provides:
- Query templates (from configs/policies.yaml)
- Simple parameter substitution
- REST connector JSON snippet scaffolds

This does NOT connect to Saviynt; it generates artifacts.
"""

from __future__ import annotations

import os
import json
from typing import Dict

import yaml

POLICIES_PATH = os.path.join(os.path.dirname(__file__), "..", "configs", "policies.yaml")


def _load_cfg() -> Dict:
    try:
        with open(POLICIES_PATH, "r") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def _templates() -> Dict[str, str]:
    cfg = _load_cfg()
    return (cfg.get("saviynt", {}) or {}).get("query_templates", {}) or {}


def run(action: str = "templates", template: str = None, params: Dict = None, purpose: str = None) -> Dict:
    try:
        action = (action or "templates").lower()
        params = params or {}

        if action in ("templates", "list"):
            ts = _templates()
            return {
                "success": True,
                "templates": [{"name": k, "preview": (v.strip().splitlines()[0] if v else "")} for k, v in ts.items()],
            }

        if action in ("query", "generate_query"):
            ts = _templates()
            if not template:
                return {"success": False, "error": "template is required"}
            if template not in ts:
                return {"success": False, "error": f"unknown template: {template}"}
            raw = ts[template]
            # Best-effort safe formatting
            try:
                rendered = raw.format(**params)
            except Exception:
                rendered = raw
            return {
                "success": True,
                "template": template,
                "query": rendered.strip(),
                "params_used": params,
            }

        if action in ("connector", "rest_connector"):
            # Minimal REST connector snippet scaffolding
            name = params.get("connectionName") or "example_rest_conn"
            base_url = params.get("baseUrl") or "https://api.example.com"
            snippet = {
                "connection": {
                    "connectionName": name,
                    "connectionType": "REST",
                    "baseUrl": base_url,
                    "auth": {
                        "type": params.get("authType", "oauth2_client_credentials"),
                        "tokenUrl": params.get("tokenUrl", "https://auth.example.com/oauth/token"),
                        "clientId": "${CLIENT_ID}",
                        "clientSecret": "${CLIENT_SECRET}",
                    },
                    "calls": {
                        "accounts": {
                            "method": "GET",
                            "path": params.get("accountsPath", "/users"),
                        }
                    }
                }
            }
            return {
                "success": True,
                "description": "REST connector scaffold (fill in endpoints, mappings, and secrets).",
                "json": snippet,
            }

        return {"success": False, "error": f"Unknown action: {action}. Use templates, query, connector."}

    except Exception as e:
        return {"success": False, "error": str(e)}


TOOL_DEF = {
    "name": "saviynt",
    "description": "Generate Saviynt SQL queries from templates, or scaffold REST connector JSON snippets.",
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["templates", "query", "connector"], "description": "Action"},
            "template": {"type": "string", "description": "Template name for action=query"},
            "params": {"type": "object", "description": "Template parameters (threshold, start_date, sod_pairs, etc.)"},
            "purpose": {"type": "string", "description": "Human-readable intent"},
        },
        "required": ["action"],
    },
}
