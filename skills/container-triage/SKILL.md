---
name: container-triage
description: A container is down, restarting, unhealthy, or someone asks whether a service is fine.
roles: [ops]
---
1. Call `container_status` first. Note status, restart count, last exit code and health.
2. If the container is running, has a restart count of 0 and is not unhealthy, say it is fine and stop. Do not ask for a restart.
3. Otherwise call `container_logs` (80 lines) and follow the log-analysis skill.
4. If the problem started after an update, or the logs mention a version or config format, `delegate` to `research`
   to read the release notes of that project (only projects you were told about).
5. Decide:
   - Exited and the logs show no crash cause: a restart may help. Follow the approval-requests skill.
   - Restarting in a loop: do not ask for a restart. A restart will not fix a loop. Report the likely cause.
   - Unhealthy but running: report what the logs show and recommend a human looks.
6. Answer with the facts you read, the cause (certain, likely or unknown), and one recommendation.
   Never say a restart happened. It waits for a person.
