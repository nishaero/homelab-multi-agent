# Guard rails

Every guard here runs in code, so a model that is confused, wrong or tricked cannot talk its
way past it. Each one has a test.

## 1. What an agent can call

Each role has a list of tools (`ROLE_TOOLS`). `check_tool` runs for every call and refuses
anything else, logging `tool_denied`. The research agent has no tool that changes anything.

## 2. What can change a system

Only three actions exist: restart an allowlisted container, switch the heat pump between
Summer and Winter, set the hot water target between 35 and 60 C. An agent never runs them.
`request_action` validates the arguments, stores an approval and notifies a human. The
action is validated again when the human approves, and only then runs. With `dry_run: true`
the approval is recorded and nothing is executed.

- Each role may request only its own actions (home cannot restart containers).
- An identical pending request is not created twice.
- A request expires after `approval_ttl_s` (6 hours).
- An approval cannot be used twice.

## 3. Loops

`LoopGuard` stops an agent that makes no progress, with three rules, because a model that
changes its arguments slightly defeats an exact match:

1. the same call more than twice;
2. the same tool with arguments over 85% similar, four times in a row;
3. more than six calls to one tool in a task, whatever the arguments.

A turn limit and a time budget are the backstop.

## 4. Untrusted text

Container logs and release notes come from outside. They are returned to the model as
`{"untrusted_content": true, ...}` with a note that they are data. A scan looks for phrases
such as "ignore previous instructions" and adds a warning and an audit row. The scan is a
flag, not a filter. The real protection is that the agent reading the text has no tool that
can cause harm without a human (see 1 and 2).

Secrets (bearer tokens, passwords, long keys) are removed from logs before the model sees
them.

## 5. Claims

Agents cannot change anything, so an answer such as "the heating was set to Winter" is
wrong. `fix_claims` appends a correction to any final answer that says a change happened.
Tool results also say plainly when data is missing ("no release notes", "no breaking
changes does not follow"), so missing information is not reported as good news.

## 6. Delegation

An agent can delegate only to the roles listed for it, the chain stops at depth 3, and a
delegated answer is labelled as advice that does not widen what the receiver may do.

## 7. Budgets

`turn_limit`, `time_budget_s`, `tool_clip_chars` and one model call at a time through the
gate.

## What is not covered

- A wrong recommendation. The model can misread data. A human reads every answer and
  approves every change.
- Injection phrased in a way the scan does not know. The design assumes it can happen.
- The Home Assistant token. Use a read only user. The code never sends a service call
  except through an approved action, but a token with more rights is more risk than needed.
