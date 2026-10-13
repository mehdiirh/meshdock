# Tunnel Manager development contract

- This is an open-source control plane. Never commit production IPs, hostnames, credentials, private keys, database files, logs, or user topology exports. Use RFC 5737 addresses in examples.
- Backend lives in backend/, frontend in frontend/. Keep adapters in backend/app/methods; extend the registry rather than adding method-specific branches to API handlers.
- Default tests use simulated SSH and isolated state. Never connect to or change a real server unless the human explicitly authorizes that specific deployment.
- All mutating topology operations require authentication, optimistic revision checks, audit entries, and durable reconciliation jobs. Coordinates and other presentation changes must not deploy remote resources.
- Secrets are encrypted at rest and are never returned after creation. Logs, previews, errors, and exports must not reveal secrets. Pin SSH host keys; never auto-trust changes.
- Own only tm-* units, explicitly namespaced paths/interfaces/firewall chains. Never flush global firewall tables, rewrite default routes, or edit unrelated Xray/Nginx/SSH configuration.
- Preserve previous generations until health checks pass. Multi-host rollback is coordinated and can require recovery after connectivity loss; do not claim distributed atomicity or exactly-once execution.
- Cleanup removes owned resources, not unrelated software or packages shared with other applications.
- Every new API message and UI string needs English and Persian translations. Persian layout is RTL; network addresses and code remain LTR.
- Validate with pytest, frontend typecheck/build, UI tests, and Docker Compose config. Test failure, retry, rollback, concurrent revisions, auth, redaction, and cleanup.
- Use small commits prefixed [ADD], [UPDATE], or [BUGFIX]. Record assumptions and open product decisions in docs/DECISIONS.md. Be explicit about unverified environments.
