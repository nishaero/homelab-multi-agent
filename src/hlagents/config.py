"""Configuration: a YAML file for structure, environment variables for secrets."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class Config:
    ollama_url: str = "http://localhost:11434"
    model: str = "qwen3.8:27b"
    num_ctx: int = 16384
    db_path: str = "hlagents.db"

    # Nothing that changes a system runs unless dry_run is false AND a human approved it.
    dry_run: bool = True

    max_depth: int = 3            # delegation chain limit
    turn_limit: int = 10          # model turns per task
    time_budget_s: int = 240      # wall clock per task
    tool_clip_chars: int = 4000   # one tool result
    max_calls_per_tool: int = 6   # per task, any arguments
    approval_ttl_s: int = 6 * 3600

    containers: list[str] = field(default_factory=list)        # allowlist for logs and restarts
    ha_prefixes: list[str] = field(default_factory=lambda: ["sensor.", "weather.", "climate.", "water_heater.", "binary_sensor."])
    heat_pump_entity: str = "climate.heat_pump"
    water_heater_entity: str = "water_heater.heat_pump"
    weather_entity: str = "weather.home"
    known_entities: dict[str, str] = field(default_factory=dict)   # entity id -> what it is, shown to the home agent
    github_repos: list[str] = field(default_factory=list)       # "owner/name" allowlist for changelogs
    memory_url: str = ""                                        # optional agent-memory API
    ntfy_url: str = ""                                          # optional, for approval requests
    serve_host: str = "127.0.0.1"                               # alert intake, see `hlagents serve`
    serve_port: int = 8110
    api_host: str = "127.0.0.1"                                 # remote API, enabled when API_TOKEN is set
    api_port: int = 8111
    mcp_host: str = "127.0.0.1"                                 # MCP server for an assistant, `hlagents mcp`
    mcp_port: int = 8112
    ha_notify_services: list[str] = field(default_factory=list) # e.g. ["mobile_app_phone_1"]; approval buttons
    ntfy_topic: str = ""

    ha_url: str = ""
    ha_token: str = ""
    memory_token: str = ""
    intake_token: str = ""
    api_token: str = ""
    mcp_secret: str = ""

    @classmethod
    def load(cls, path: str | None = None) -> "Config":
        data: dict = {}
        p = Path(path or os.environ.get("HLAGENTS_CONFIG", "config.yaml"))
        if p.exists():
            data = yaml.safe_load(p.read_text()) or {}
        known = set(cls.__dataclass_fields__)
        cfg = cls(**{k: v for k, v in data.items() if k in known and k not in ("ha_url", "ha_token", "memory_token", "intake_token", "api_token", "mcp_secret")})
        cfg.ha_url = os.environ.get("HA_URL", data.get("ha_url", "")).rstrip("/")
        cfg.ha_token = os.environ.get("HA_TOKEN", "")
        cfg.memory_token = os.environ.get("MEMORY_TOKEN", "")
        cfg.intake_token = os.environ.get("INTAKE_TOKEN", "")
        cfg.api_token = os.environ.get("API_TOKEN", "")
        cfg.mcp_secret = os.environ.get("MCP_SECRET", "")
        cfg.ollama_url = os.environ.get("OLLAMA_URL", cfg.ollama_url).rstrip("/")
        cfg.model = os.environ.get("HLAGENTS_MODEL", cfg.model)
        return cfg
