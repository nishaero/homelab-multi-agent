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
| Home Assistant | Read only tools. A change goes through an approved action. |

## Safe to try

- Start it by hand, watch it, stop it. The systemd unit in `systemd/` is provided but is not
  enabled.
- Remove it by stopping the process and deleting the project and its `.db` file.
- Before and after a live trial, a snapshot of container states, restart counts, heating
  settings and automation states was identical.

## Going from dry run to live

1. Run in dry run for a while and read `hlagents audit` for a few requests.
2. Give it a Home Assistant token for a user that can only read.
3. Set `dry_run: false` only when you are happy with what it proposes. A human still
   approves each change.
