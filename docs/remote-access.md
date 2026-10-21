# Remote access

Three ways to reach the team without a terminal. None of them can run a tool or an action
directly, and none exposes anything to the internet by itself.

| Way | For | Can it approve a change? |
|---|---|---|
| Phone notification buttons | Deciding a change, anywhere | Yes, with a one time token |
| HTTP API | A UI or a script on the local network | Yes, with the API token |
| MCP server | An assistant such as Home Assistant's voice assistant | No |

## 1. Phone buttons

When an agent asks for approval, `notify_approval` sends a Home Assistant notification to the
phones in `ha_notify_services`, with Approve and Deny buttons. Pressing one fires a
`mobile_app_notification_action` event. A listener (`ha_bridge.py`) receives it over the Home
Assistant websocket and decides the approval, then replaces the notification with the outcome.

Each button carries a one time token that exists only in that notification and in the database.
A press with a missing or wrong token is ignored and written to the audit trail
(`approval_bad_token`). A request still expires after `approval_ttl_s`, and cannot be decided twice.

```yaml
ha_notify_services: [mobile_app_phone_1]
```

Needs `HA_URL` and a `HA_TOKEN` that can call the notify service and subscribe to events.

## 2. HTTP API

Enabled when `API_TOKEN` is set. Bound to `api_host` (default `127.0.0.1`).

```
POST /requests              {"goal": "..."}      -> {"id": N}
GET  /requests                                   -> recent requests
GET  /requests/N                                 -> status, result, steps, pending approvals
GET  /requests/N/audit                           -> the audit trail
GET  /approvals                                  -> waiting for a decision (the token is never shown)
POST /approvals/N/approve | /approvals/N/deny
```

Every call needs `Authorization: Bearer <API_TOKEN>`. With no token configured, every call is refused.
Keep it on the local network. If you put a UI in front of it, let the UI do the login.

## 3. MCP server for an assistant

`hlagents mcp` serves three tools: `ask_team` (submit a request and wait up to 25 seconds for the
answer), `team_status` and `list_pending_approvals`. There is no approve tool on purpose: anyone who
can speak to a speaker, or a text to speech message, could trigger it.

The endpoint is `http://<host>:8112/mcp-<MCP_SECRET>`, so a client needs the host and the secret.
It calls the HTTP API, so it needs `API_TOKEN` too.

To use it from Home Assistant, add it as an MCP integration entry. Adding the entry does not give it
to any assistant. To let a voice assistant use it, enable it in that assistant's tool list. Try it on a
separate assistant first: more tools in a small voice model's list can slow it down or confuse it.

## Security notes

- Open the MCP port only to the machine that needs it (for example one firewall rule for the Home
  Assistant address), and keep `MCP_SECRET` and `API_TOKEN` in a file readable only by you.
- The service is dry run until you change that. A pressed Approve button on a dry run only records the
  action.
- All three paths end in the same code (`approvals.py`), so the rules (token, expiry, validation,
  one decision) are the same everywhere.
