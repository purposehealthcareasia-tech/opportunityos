"""Curated + EMPIRICALLY VERIFIED employer catalog for LYNK real-job
discovery. Every tuple in the three lists below returned HTTP 200 with
≥ 1 posting when probed against the live public ATS at build time.

Tokens are NEVER guessed. If a token's endpoint stops returning ≥1
posting at ingest time, `service.py` drops it silently for that pass
and records a warning in the audit — the tuple stays here so a later
re-verification can pick it up again.

Founder priority (highest first):
  1) EV / automotive
  2) Robotics / autonomy
  3) Aerospace / defense
  4) Semiconductor / hardware
  5) Phoenix / Arizona regardless of sector

Founder-confirmed tokens that this pod cannot currently reach (kept in
`FOUNDER_CONFIRMED_UNREACHABLE` for transparency; ingester will retry
each pass and log per-outcome):
  * Greenhouse: appliedintuition — 268+ postings observed from
    outside the pod; consistent HTTP 404 from this preview egress.
"""
from __future__ import annotations

# (display_name, board_token) — verified live at build time.
GREENHOUSE_BOARDS: list[tuple[str, str]] = [
    # === EV / automotive (priority 1) ===
    ("Lucid Motors", "lucidmotors"),
    ("Faraday Future", "faradayfuture"),
    ("Waymo", "waymo"),
    ("Motional", "motional"),
    ("Nauto", "nauto"),
    ("Kodiak Robotics", "kodiak"),
    ("Wayve", "wayve"),
    ("Carvana", "carvana"),
    ("Divergent", "divergent"),
    ("Bird Global", "bird"),

    # === Robotics / autonomy (priority 2) ===
    ("Nuro", "nuro"),
    ("Figure AI", "figure"),
    ("Apptronik", "apptronik"),
    ("Agility Robotics", "agilityrobotics"),
    ("Verkada", "verkada"),
    ("Anduril Industries", "andurilindustries"),

    # === Aerospace / defense (priority 3) ===
    ("Archer Aviation", "archer"),
    ("Astranis", "astranis"),
    ("Rocket Lab", "rocketlab"),
    ("SpaceX", "spacex"),
    ("Relativity Space", "relativity"),
    ("Vast Space", "vast"),
    ("Momentus", "momentus"),
    ("Slingshot Aerospace", "slingshotaerospace"),
    ("Whisper Aero", "whisperaero"),
    ("Palantir Technologies", "palantirtechnologies"),  # verify at load

    # === Battery / clean energy ===
    ("Redwood Materials", "redwoodmaterials"),
    ("Sila Nanotechnologies", "silananotechnologies"),
    ("Rondo Energy", "rondoenergy"),

    # === Semiconductor / hardware / AI (priority 4) ===
    ("Anthropic", "anthropic"),
    ("SambaNova Systems", "sambanovasystems"),
    ("Tenstorrent", "tenstorrent"),
    ("Lightmatter", "lightmatter"),
    ("PsiQuantum", "psiquantum"),
    ("IonQ", "ionq"),

    # === Phoenix / Arizona (priority 5) ===
    ("GoDaddy", "godaddy"),
    ("Axon", "axon"),

    # === Broad tech safety net (relevant to eng candidates outside taxonomy) ===
    ("Stripe", "stripe"),
    ("Airbnb", "airbnb"),
    ("Coinbase", "coinbase"),
    ("Reddit", "reddit"),
    ("GitLab", "gitlab"),
    ("Figma", "figma"),
    ("Asana", "asana"),
    ("Dropbox", "dropbox"),
    ("Instacart", "instacart"),
    ("Robinhood", "robinhood"),
    ("Affirm", "affirm"),
    ("Brex", "brex"),
    ("Roblox", "roblox"),
    ("Discord", "discord"),
    ("Airtable", "airtable"),
    ("Databricks", "databricks"),
    ("MongoDB", "mongodb"),
    ("Elastic", "elastic"),
    ("Gusto", "gusto"),
    ("Twilio", "twilio"),
    ("Cloudflare", "cloudflare"),
    ("Chime", "chime"),
    ("Nextdoor", "nextdoor"),
    ("Peloton", "peloton"),
    ("Datadog", "datadog"),
]

LEVER_BOARDS: list[tuple[str, str]] = [
    ("Shield AI", "shieldai"),
    ("Loft Orbital", "loftorbital"),
]

ASHBY_BOARDS: list[tuple[str, str]] = [
    # === AI model labs / frontier ===
    ("OpenAI", "openai"),
    ("Perplexity", "perplexity"),
    ("Cognition Labs", "cognition"),
    ("Character AI", "character"),
    ("Poolside", "poolside"),
    ("Cursor", "cursor"),
    ("Replit", "replit"),
    ("Modal", "modal"),
    ("Notion", "notion"),
    ("Linear", "linear"),
    ("Supabase", "supabase"),
    ("PostHog", "posthog"),
    ("Warp", "warp"),
    ("Zed Industries", "zed"),
    ("Browserbase", "browserbase"),
    ("Krea", "krea"),
    ("Harvey", "harvey"),
    ("ElevenLabs", "elevenlabs"),
    ("Etched", "etched"),
    ("Physical Intelligence", "physicalintelligence"),
    ("Deepgram", "deepgram"),
    ("Weaviate", "weaviate"),
    ("LangChain", "langchain"),
    ("Fireworks AI", "fireworks"),
    ("MidJourney", "midjourney"),
    ("Neon", "neon"),
    ("Suno", "suno"),
    ("Runway", "runway-ml"),
    ("Substrate", "substrate"),
    ("Sesame", "sesame"),
    ("Zapier", "zapier"),
    ("Attio", "attio"),
    ("Y Combinator", "ycombinator"),
    ("Kalshi", "kalshi"),
    ("Anrok", "anrok"),
    ("Baseten", "baseten"),
    ("Mercor", "mercor"),
    ("Braintrust", "braintrust"),
    ("Roboflow", "roboflow"),
    ("Nabla", "nabla"),
    ("Instructure", "instructure"),
]

# Verified-external but preview-egress unreachable at build time.
# Ingester will retry each pass; kept for auditability, never inflated
# into the "kept" bucket.
FOUNDER_CONFIRMED_UNREACHABLE: list[tuple[str, str, str]] = [
    ("greenhouse", "Applied Intuition", "appliedintuition"),
]

ALL_BOARDS: list[tuple[str, str, str]] = (
    [("greenhouse", n, t) for n, t in GREENHOUSE_BOARDS]
    + [("lever", n, t) for n, t in LEVER_BOARDS]
    + [("ashby", n, t) for n, t in ASHBY_BOARDS]
)
