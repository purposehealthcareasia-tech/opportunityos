# Fynd × LYNK Collider — connection readiness

This bundle is an incremental integration against Fynd's current Emergent
workspace (HEAD `5298bd01`, 196 commits ahead of the old public GitHub branch).
It does **not** enable user scans, crawl the Internet, ingest jobs, submit job
applications, charge customers, or deploy Collider infrastructure.

## Included

- A bounded, fixed-origin Python client for the existing Collider gateway.
- A `lynk_collider` provider in Fynd's existing admin integration registry.
- Admin/support can inspect status; existing admin-only controls own probes.
- No network activity during registration, boot snapshots, or status reads.
- Successful probes validate gateway health and capability JSON only.
- Configured credentials are not evidence of connection; a successful probe
  expires after five minutes. Source-provider readiness is not claimed.
- Connection-only UI notice and an explicit discovery category.
- No public run, global evidence, board-memory, or submission routes.

## Server-only configuration

`FYND_COLLIDER_BASE_URL`, `FYND_COLLIDER_TOKEN`, and explicitly
`FYND_COLLIDER_ENABLED=true` are required to permit connection probes.
Do not put these values into React build variables or committed files.
The dashboard Enable button cannot bypass the explicit server opt-in.

The current gateway accepts loopback Host headers. A remote HTTPS deployment
needs an operator-reviewed private proxy, persistent storage, and correct
network isolation. The client never spoofs Host or follows redirects.
Never configure a production site to use a user's laptop localhost endpoint.

## Gates before customer launch

1. Provision and verify a private gateway and its actual source providers.
2. Implement owner-scoped run and evidence storage and retention/deletion.
3. Propagate Fynd's registry policy and kill switches to every network hop.
4. Add budget reservations, quotas, timeout reconciliation, and usage receipts.
5. Review licensing and run real staging integration/security tests.

Existing discovery, entity-resolution, source-policy, and liveness logic is
preserved. No fabricated Internet-coverage percentage is supplied.

## Validation

The standalone client's tests use HTTPX MockTransport and make no live requests.
Provider tests must run inside the actual Fynd backend so they exercise the
real BaseProvider and registry contracts. Remote installation and test results
are recorded separately; this document is not a deployment receipt.

`existing.patch` contains narrow changes to four existing files. The generated
`collider-readiness.patch` includes those changes and the new source/tests.
Apply only after `git apply --check`; reverse only this patch if rollback is
needed. Never reset the workspace or push its unrelated unpublished commits.
