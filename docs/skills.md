# Agent skills

A skill is a short procedure written for an agent: when to use it and the steps to follow. Skills are plain
files, one folder each, so a person can read, review and change them without touching code.

```
skills/
  container-triage/SKILL.md      ops        a container is down, restarting or unhealthy
  log-analysis/SKILL.md          ops, research   reading logs, untrusted text, what counts as an error
  release-notes-review/SKILL.md  research   what changed, breaking markers, no notes is not good news
  heating-decision/SKILL.md      home       the Winter or Summer rule for underfloor heating
  hot-water-targets/SKILL.md     home       tank targets and how solar changes them
  approval-requests/SKILL.md     ops, home  how to ask a person to approve a change
```

## Format

```markdown
---
name: container-triage          # must match the folder name
description: When to use this skill, in one line.
roles: [ops]                    # which agents get it
---
1. Numbered steps, in plain language.
```

## How they are used

- The loader reads them once at start up. A broken file (no header, unknown role, empty, name does not match the
  folder) is skipped and logged, never fatal.
- Each task gets only the skills for its role, added to the agent's instructions. A research task never sees the
  heating rule.
- The audit trail records which skills were loaded and a fingerprint of their text, so you can tell which version of
  a skill an answer came from.

## What skills cannot do

- **They do not widen permissions.** A skill is text. The tools and actions an agent can call are decided in code
  per role. A test checks that every tool and action a skill names exists for the roles that get it, and another
  that a skill telling the research agent to restart something still gets refused.
- **Agents cannot write or change them.** Skills are files in the repository, changed by a person and reviewed like
  code.
- **They are trusted text.** Unlike logs and release notes, which are labelled as untrusted data.

## Adding one

1. Create `skills/<name>/SKILL.md` with the header above.
2. Use only tools and actions the listed roles already have (the test will tell you if not).
3. Run `pytest`. Restart the service to load it.
