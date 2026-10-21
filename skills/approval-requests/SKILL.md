---
name: approval-requests
description: You want to change something. Use this every time you call request_action.
roles: [ops, home]
---
1. You cannot change anything yourself. `request_action` asks a person and nothing happens until they approve.
2. One action per request. Use the exact action name and argument names from your list.
3. Write the reason with measured facts and where you got them: "restart count 3, exited with code 137,
   checked with container_status".
4. Say what you expect to happen and how to undo it ("set it back to 50 C").
5. If the call is refused, read the error. It lists valid actions and an example. Fix the arguments once.
   Do not repeat the same request.
6. After the call, say it is waiting for approval and give the approval number. Never say it was done.
