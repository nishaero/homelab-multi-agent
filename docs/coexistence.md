# Running beside the existing setup

The goal was to add a team of agents without changing or risking what already works.

## What it does not touch

- No existing agent, script, timer, container or Home Assistant automation is modified.
- It has its own SQLite file and its own process. Stopping it removes nothing.
- It does not take over any job. The existing ops agent keeps doing updates, backups and
  rollbacks on its own schedule.
- Dry run is the default. Even an approved action is only recorded until `dry_run` is set to
  false.

## How it complements

| Existing piece | How hlagents uses it |
|---|---|
| Ollama | Same server and models. A gate serialises its own calls so it does not stack requests on one GPU. |
| Shared memory service | Optional: leaves a note when a request finishes, and agents can search past notes. |
| Alertmanager | Optional webhook turns an alert into a request, so an existing alert gets an investigation. |
| ntfy | Optional: approval requests are pushed to a phone. |
| Home Assistant | Read only tools. A change goes through an approved action. Phone buttons use its notifications and events. An MCP entry can be added so its assistant can ask the team. The entry is not attached to any assistant until you choose. |

## Safe to try

- It can run by hand (`hlagents run`) or as two user services, `hlagents` (workers, API, phone buttons) and
  `hlagents-mcp`. The unit files are in `systemd/` and are not enabled until you do it. Stop them with
  `systemctl --user stop hlagents hlagents-mcp`, and `disable` to keep them off after a reboot.
- Remove it by stopping the process and deleting the project and its `.db` file.
- Before and after a live trial, a snapshot of container states, restart counts, heating
  settings and automation states was identical.

## Going from dry run to live

1. Run in dry run for a while and read `hlagents audit` for a few requests.
2. Give it a Home Assistant token for a user that can only read.
3. Set `dry_run: false` only when you are happy with what it proposes. A human still
   approves each change.
