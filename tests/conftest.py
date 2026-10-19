import os
from pathlib import Path

# The live evaluation (`pytest -m live`) needs a real Anthropic key. Take it
# from the local .env when the shell does not export one; nothing else is read
# from there, so the offline tests never see real Supabase settings.
_env = Path(__file__).resolve().parent.parent / ".env"
if "ANTHROPIC_API_KEY" not in os.environ and _env.exists():
    for line in _env.read_text().splitlines():
        name, _, value = line.partition("=")
        if name.strip() == "ANTHROPIC_API_KEY" and value.strip():
            os.environ["ANTHROPIC_API_KEY"] = value.strip().strip("\"'")

# Settings are read at import time by app.main; tests never touch the network.
os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon-key")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
