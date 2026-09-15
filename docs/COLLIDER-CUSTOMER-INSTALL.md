# Fynd customer scans — installation gate

This package adds a default-off customer scan bridge and Research controls to
the existing Fynd/Emergent application. It is not a standalone app or crawler
deployment. It assumes the previously installed Collider domain and Research
account library. Do not apply it to a different baseline by force.

## Install without enabling collection

1. Preserve the current Emergent changes and record the current release/source
   state. Do not reset, overwrite unrelated work, push, or republish implicitly.
2. Upload `collider-customer-integration.patch` and verify its SHA-256 against the
   accompanying release receipt. In `/app`, run
   `git apply --check collider-customer-integration.patch`. Stop on any mismatch;
   review the actual source and rebuild the patch instead of forcing it.
3. Apply with `git apply collider-customer-integration.patch`. Compare installed
   source hashes against `customer-package-manifest.json`. The manifest's new
   and Research-page hashes must match; its three wiring edits are contextual
   changes, not complete-file hashes.
4. Confirm `backend/server.py` mounts the customer router and the idempotency
   middleware bypasses exactly `/api/v1/collider/scans` and its descendants
   before the old cached-response path. This is a security requirement.
5. Leave `FYND_COLLIDER_CUSTOMER_ENABLED` unset or `false`. Restart only the
   development backend/frontend using the existing Emergent workflow. Do not
   expose the legacy operator gateway to customers.
6. Run the new isolated client/router tests with `unittest` from `backend/`:
   `python -m unittest discover -s tests -p 'test_customer_collider_*.py' -q`.
   These use synthetic auth and HTTPX transport, not real accounts/providers.
   Run the actual frontend's existing Research and new scan Jest suites and
   production build. Avoid the broad backend pytest suite: its existing
   autouse fixtures may change authentication state.
7. Confirm the real signed-in Research page retains manual import/account
   library behavior, shows scanning disabled, and starts no source reads.

## Configure a private pilot only after production prerequisites

Deploy the separate customer service from the engine repository, not the old
global evidence gateway. `compose.customers.yaml` is opt-in and has no published
host port. Its policy example is disabled. Supply persistent private storage,
private TLS ingress, a reviewed source policy and server-only signing secrets.

Fynd settings (not frontend variables):

- `FYND_COLLIDER_CUSTOMER_BASE_URL`: fixed private HTTPS origin, no path/query.
- `FYND_COLLIDER_CUSTOMER_SECRET`: same signing key as the customer service.
- `FYND_COLLIDER_CUSTOMER_ENABLED=true`: only after the remaining gates pass.

Engine settings: `COLLIDER_CUSTOMER_SECRET`, `COLLIDER_CUSTOMER_DATA`,
`COLLIDER_CUSTOMER_POLICY_FILE`, and exact ingress `COLLIDER_CUSTOMER_ALLOWED_HOSTS`
as documented in `customer-service.mjs`. Keep secrets out of logs, patches,
frontend bundles, screenshots and chat. Keep engine/Fynd clocks synchronized.

Before any public activation: enforce every-hop outbound access controls,
cross-customer origin pacing, evidence retention/deletion and backup/restore;
approve hosting/provider costs and applicable source/licensing requirements;
verify two real staging accounts through scan, cancellation/recovery, report,
save/reopen, account isolation and quota failures. Measure cost/latency/load.
Configured availability alone does not prove provider readiness.

## Release and rollback

Publish only after these gates and review of the complete existing unpublished
Fynd changes. Verify the public build separately. No public release is included
in this package. Disable the feature flag to stop new bridge requests; the
engine policy kill switch separately denies new source admissions. Neither
removes previously retained data or necessarily cancels in-flight reads. Do not
delete customer storage as a rollback step.

This remains a bounded pilot implementation, not unlimited crawling, guaranteed
accuracy, access to restricted platforms, or a measured internet-coverage claim.
