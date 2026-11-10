import os
from pathlib import Path

# Folder that holds this file (the "app" folder)
BASE_DIR = Path(__file__).resolve().parent

# Where the SQLite file is saved. Default: next to the app folder.
DB_PATH = Path(os.getenv("PULSE_DB", str(BASE_DIR.parent / "pulse.db")))

# Seconds to wait between two rounds of checks (never less than 10)
CHECK_INTERVAL = max(10, int(os.getenv("PULSE_INTERVAL_SECONDS", "10")))

# How long to wait for an endpoint to answer before giving up
REQUEST_TIMEOUT = 8.0

# Old check rows are deleted after this many days so the file stays small
KEEP_DAYS = max(1, int(os.getenv("PULSE_KEEP_DAYS", "14")))

# Sent with every request so site owners can see who is calling
USER_AGENT = "RK-API-Pulse/2.0 (RK_Python_1)"

# Endpoints added the very first time the app starts
SAMPLE_ENDPOINTS = [
    ("HTTPBin Status", "https://httpbin.org/status/200", 1500),
    ("GitHub API", "https://api.github.com", 1500),
    ("JSONPlaceholder", "https://jsonplaceholder.typicode.com/posts/1", 1500),
]
