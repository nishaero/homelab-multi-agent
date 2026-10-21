"""Skills: reusable procedures for the agents, kept as plain files a person can read and review.

Each skill is `skills/<name>/SKILL.md`: a small header (name, description, roles) and the steps.
The loader reads them once at start up. A role gets the skills that list it. Agents cannot write or
change skills, and a skill can only name tools the role already has, so a skill never widens
what an agent is allowed to do. The text and a hash are recorded in the audit trail of each task.
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path

import yaml

log = logging.getLogger("hlagents.skills")


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    roles: tuple[str, ...]
    body: str
    path: str


def parse(text: str, path: str = "") -> Skill:
    if not text.startswith("---"):
        raise ValueError("missing header")
    _, head, body = text.split("---", 2)
    meta = yaml.safe_load(head) or {}
    name, desc, roles = meta.get("name"), meta.get("description"), meta.get("roles")
    if not (isinstance(name, str) and name and isinstance(desc, str) and desc and isinstance(roles, list) and roles):
        raise ValueError("header needs name, description and roles")
    if not body.strip():
        raise ValueError("empty skill")
    return Skill(name, desc, tuple(str(r) for r in roles), body.strip(), path)


def load(directory: str | Path, valid_roles: set[str] | None = None) -> list[Skill]:
    """Every readable skill under the directory. A broken file is skipped and logged, never fatal."""
    out: list[Skill] = []
    root = Path(directory)
    for p in sorted(root.glob("*/SKILL.md")):
        try:
            s = parse(p.read_text(), str(p))
            if valid_roles is not None and not set(s.roles) <= valid_roles:
                raise ValueError(f"unknown role in {s.roles}")
            if p.parent.name != s.name:
                raise ValueError("folder name and skill name differ")
            out.append(s)
        except Exception as e:  # noqa: BLE001
            log.warning("skipped %s: %s", p, e)
    return out


def for_role(skills: list[Skill], role: str) -> list[Skill]:
    return [s for s in skills if role in s.roles]


def prompt_block(skills: list[Skill]) -> str:
    if not skills:
        return ""
    parts = [f"## Skill: {s.name}\nUse when: {s.description}\n{s.body}" for s in skills]
    return "\n\nSkills you have (follow them when they apply):\n\n" + "\n\n".join(parts)


def fingerprint(skills: list[Skill]) -> str:
    h = hashlib.sha256()
    for s in sorted(skills, key=lambda s: s.name):
        h.update(s.name.encode() + b"\0" + s.body.encode() + b"\0")
    return h.hexdigest()[:12]
