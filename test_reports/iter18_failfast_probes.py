"""Iter18 subprocess fail-fast probes for PROD_MODE guards. Runs `python -c 'from server import app'`
under various env combos and asserts on stderr message (never printing env values themselves)."""
import os
import subprocess
import sys

BACKEND_DIR = "/app/backend"

def run(env_over):
    env = os.environ.copy()
    # scrub keys that would interfere
    for k in ("PROD_MODE", "CI_TEST_ISSUER_ENABLED", "CORS_ALLOW_ORIGINS"):
        env.pop(k, None)
    env.update(env_over)
    p = subprocess.run(
        [sys.executable, "-c", "from server import app"],
        cwd=BACKEND_DIR, env=env, capture_output=True, text=True, timeout=60
    )
    return p.returncode, p.stderr

def main():
    results = {}

    # (a) CI issuer conflict
    rc, err = run({"PROD_MODE": "true", "CI_TEST_ISSUER_ENABLED": "true",
                   "CORS_ALLOW_ORIGINS": "https://x.example"})
    expected = "SECURITY: CI_TEST_ISSUER_ENABLED cannot be true in PROD_MODE=true"
    ok = rc != 0 and expected in err
    results["a_ci_issuer_conflict"] = {"pass": ok, "rc": rc, "matched": expected in err}
    print(f"(a) CI issuer conflict: {'PASS' if ok else 'FAIL'} rc={rc} matched={expected in err}")

    # (b) empty CORS in prod
    rc, err = run({"PROD_MODE": "true", "CI_TEST_ISSUER_ENABLED": "false",
                   "CORS_ALLOW_ORIGINS": ""})
    expected = "SEC-004: PROD_MODE=true requires a non-empty CORS_ALLOW_ORIGINS"
    ok = rc != 0 and expected in err
    results["b_empty_cors"] = {"pass": ok, "rc": rc, "matched": expected in err}
    print(f"(b) Empty CORS in prod: {'PASS' if ok else 'FAIL'} rc={rc} matched={expected in err}")

    # (c) clean prod boot
    rc, err = run({"PROD_MODE": "true", "CI_TEST_ISSUER_ENABLED": "false",
                   "CORS_ALLOW_ORIGINS": "https://prod.example.com"})
    ok = rc == 0
    results["c_clean_prod_boot"] = {"pass": ok, "rc": rc, "stderr_snippet_len": len(err)}
    print(f"(c) Clean prod boot: {'PASS' if ok else 'FAIL'} rc={rc}")
    if not ok:
        print("STDERR (truncated):", err[-500:])

    all_pass = all(r["pass"] for r in results.values())
    print(f"\nOVERALL: {'PASS' if all_pass else 'FAIL'} ({sum(1 for r in results.values() if r['pass'])}/3)")
    return 0 if all_pass else 1

if __name__ == "__main__":
    sys.exit(main())
