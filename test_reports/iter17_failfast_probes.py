"""Subprocess fail-fast guard probes for iteration 17.

Verifies:
  1. PROD_MODE=true + CI_TEST_ISSUER_ENABLED=true → server refuses to start.
  2. PROD_MODE=true + CORS_ALLOW_ORIGINS='' → server refuses to start.
  3. PROD_MODE=true + CI flag off + non-empty CORS → module imports cleanly
     (no fail-fast trigger).

We invoke `python -c "import server"` in a subprocess with modified env so
the top-level guards at server.py:55-59 and 151-155 fire during import.
"""
import os
import subprocess
import sys

BACKEND_DIR = "/app/backend"
PY = sys.executable


def run_import(env_overrides: dict) -> tuple[int, str, str]:
    env = os.environ.copy()
    # Strip real .env values by explicitly setting these; pydantic-settings
    # will still read backend/.env for anything we don't override, but the
    # subprocess CWD ensures the .env file is picked up either way. We only
    # override the vars under test.
    env.update(env_overrides)
    proc = subprocess.run(
        [PY, "-c", "import server"],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return proc.returncode, proc.stdout, proc.stderr


def test_prod_mode_plus_ci_issuer_refuses_to_start():
    rc, out, err = run_import({
        "PROD_MODE": "true",
        "CI_TEST_ISSUER_ENABLED": "true",
        "CORS_ALLOW_ORIGINS": "https://example.com",
    })
    assert rc != 0, f"Expected non-zero exit, got {rc}. stderr={err}"
    assert "CI_TEST_ISSUER_ENABLED cannot be true in PROD_MODE" in err, (
        f"Expected CI-issuer guard message in stderr. Got: {err}"
    )
    print("[PASS] PROD_MODE + CI_TEST_ISSUER_ENABLED → refused to start")


def test_prod_mode_empty_cors_refuses_to_start():
    rc, out, err = run_import({
        "PROD_MODE": "true",
        "CI_TEST_ISSUER_ENABLED": "false",
        "CORS_ALLOW_ORIGINS": "",
    })
    assert rc != 0, f"Expected non-zero exit, got {rc}. stderr={err}"
    assert "PROD_MODE=true requires a non-empty CORS_ALLOW_ORIGINS" in err, (
        f"Expected empty-CORS guard message in stderr. Got: {err}"
    )
    print("[PASS] PROD_MODE + empty CORS → refused to start")


def test_prod_mode_valid_config_imports_cleanly():
    rc, out, err = run_import({
        "PROD_MODE": "true",
        "CI_TEST_ISSUER_ENABLED": "false",
        "CORS_ALLOW_ORIGINS": "https://example.com",
    })
    # It should at least pass the two fail-fast guards. Because the module
    # imports include DB pool bootstrap paths etc., a clean rc==0 is expected
    # for pure import. If not, print stderr so we can see why.
    assert rc == 0, f"Expected clean import, got rc={rc}. stderr={err}"
    print("[PASS] PROD_MODE + valid CORS + CI issuer disabled → imports cleanly")


if __name__ == "__main__":
    test_prod_mode_plus_ci_issuer_refuses_to_start()
    test_prod_mode_empty_cors_refuses_to_start()
    test_prod_mode_valid_config_imports_cleanly()
    print("\nAll 3 fail-fast subprocess probes passed.")
