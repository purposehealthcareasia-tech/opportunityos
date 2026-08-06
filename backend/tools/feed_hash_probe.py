"""Byte-identical feed proof — Phase 1 Step (ii).

Fetches /api/v1/jobs/feed as fixture-ead@ via cookie auth, normalizes
volatile fields (per PHASE-1-EVIDENCE §0), computes md5 and reports.

Usage: python3 backend/tools/feed_hash_probe.py [output_path]
"""
import hashlib, json, os, subprocess, sys, tempfile

BASE = os.environ.get("BASE") or subprocess.check_output(
    ["bash","-lc","grep REACT_APP_BACKEND_URL /app/frontend/.env | cut -d= -f2"]).decode().strip()

def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        sys.stderr.write(r.stderr)
        sys.exit(r.returncode)
    return r.stdout

def fetch_feed():
    cookies = tempfile.NamedTemporaryFile(delete=False, suffix=".txt").name
    run(["curl","-fs","-X","POST",f"{BASE}/api/v1/auth/login",
         "-H","Content-Type: application/json",
         "-d",'{"email":"fixture-ead@opportunityos.dev","password":"Fixture!Test1"}',
         "-c",cookies])
    csrf = None
    with open(cookies) as f:
        for line in f:
            if "oppos_csrf" in line:
                csrf = line.strip().split("\t")[-1]
    body = run(["curl","-fs",f"{BASE}/api/v1/jobs/feed","-b",cookies,"-H",f"X-CSRF-Token: {csrf}"])
    return json.loads(body)

_VOLATILE = {"discovery","polled_at","last_polled_at","first_seen","posted_at","served_at",
             "cache_key","fetched_at","last_verified","closed_detected_at","last_seen"}
def _scrub(o):
    if isinstance(o, dict):
        return {k:_scrub(v) for k,v in o.items() if k not in _VOLATILE}
    if isinstance(o, list):
        return [_scrub(x) for x in o]
    return o

def normalize(feed):
    out = _scrub(feed)
    if isinstance(out.get("passing"), list):
        out["passing"] = sorted(out["passing"], key=lambda x: x.get("id",""))
    if isinstance(out.get("excluded"), list):
        out["excluded"] = sorted(out["excluded"], key=lambda x: x.get("id",""))
    return out

def main():
    feed = fetch_feed()
    norm = normalize(feed)
    blob = json.dumps(norm, sort_keys=True, separators=(",",":"), default=str).encode()
    md5 = hashlib.md5(blob).hexdigest()
    passing_ids = [(p.get("id","")[:8], p.get("score")) for p in norm.get("passing",[])]
    print(f"md5={md5}")
    print(f"passing_count={len(norm.get('passing',[]))}")
    print(f"excluded_count={len(norm.get('excluded',[]))}")
    print("passing_scores=")
    for pid, sc in sorted(passing_ids):
        print(f"  {pid}  {sc}")
    if len(sys.argv) > 1:
        with open(sys.argv[1],"wb") as f: f.write(blob)
        print(f"wrote {sys.argv[1]}")

if __name__=="__main__": main()
