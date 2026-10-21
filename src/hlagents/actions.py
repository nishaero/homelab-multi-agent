"""The only things that can change a system, and the only way they run.

An agent never executes one of these. It asks for one (`request_action`), a human approves
it from the CLI, and then the action runs with arguments that are validated again here.
With `dry_run` on, an approved action is recorded but not carried out.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import Callable

import httpx

from .config import Config


class ActionError(Exception):
    pass


@dataclass
class Action:
    summary: str
    example: dict
    validate: Callable[[Config, dict], dict]
    run: Callable[[Config, dict], str]


def _need(args: dict, key: str) -> object:
    if key not in args:
        raise ActionError(f"missing argument '{key}'")
    return args[key]


def _v_restart(cfg: Config, a: dict) -> dict:
    name = str(_need(a, "container"))
    if name not in cfg.containers:
        raise ActionError(f"container '{name}' is not in the allowlist")
    return {"container": name}


def _r_restart(cfg: Config, a: dict) -> str:
    p = subprocess.run(["docker", "restart", a["container"]], capture_output=True, text=True, timeout=120)
    if p.returncode:
        raise ActionError(p.stderr.strip()[:300] or "docker restart failed")
    return f"restarted {a['container']}"


def _v_preset(cfg: Config, a: dict) -> dict:
    preset = str(_need(a, "preset"))
    if preset not in ("Summer", "Winter"):
        raise ActionError("preset must be Summer or Winter")
    return {"preset": preset}


def _ha(cfg: Config, domain: str, service: str, data: dict) -> None:
    if not (cfg.ha_url and cfg.ha_token):
        raise ActionError("Home Assistant is not configured")
    r = httpx.post(f"{cfg.ha_url}/api/services/{domain}/{service}", json=data, timeout=20,
                   headers={"Authorization": f"Bearer {cfg.ha_token}"})
    r.raise_for_status()


def _r_preset(cfg: Config, a: dict) -> str:
    _ha(cfg, "climate", "set_preset_mode", {"entity_id": cfg.heat_pump_entity, "preset_mode": a["preset"]})
    return f"heat pump preset set to {a['preset']}"


def _v_hot_water(cfg: Config, a: dict) -> dict:
    try:
        t = int(_need(a, "temperature"))
    except (TypeError, ValueError):
        raise ActionError("temperature must be a whole number") from None
    if not 35 <= t <= 60:
        raise ActionError("temperature must be between 35 and 60")
    return {"temperature": t}


def _r_hot_water(cfg: Config, a: dict) -> str:
    _ha(cfg, "water_heater", "set_temperature", {"entity_id": cfg.water_heater_entity, "temperature": a["temperature"]})
    return f"hot water target set to {a['temperature']} C"


ACTIONS: dict[str, Action] = {
    "restart_container": Action("Restart one allowlisted container", {"container": "<name>"}, _v_restart, _r_restart),
    "set_heating_preset": Action("Switch the heat pump between Summer and Winter", {"preset": "Winter"}, _v_preset, _r_preset),
    "set_hot_water_target": Action("Set the hot water tank target, 35 to 60 C", {"temperature": 50}, _v_hot_water, _r_hot_water),
}


def validate(action: str, args: dict, cfg: Config) -> dict:
    if action not in ACTIONS:
        raise ActionError(f"unknown action '{action}'")
    return ACTIONS[action].validate(cfg, args or {})


def execute(action: str, args: dict, cfg: Config) -> str:
    args = validate(action, args, cfg)
    if cfg.dry_run:
        return f"dry run: would run {action} {args}"
    return ACTIONS[action].run(cfg, args)
