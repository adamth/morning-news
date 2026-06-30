#!/bin/sh
set -e

python <<'PY'
import os
import sys

data_dir = os.environ.get("DATA_DIR", "/data")
os.makedirs(data_dir, exist_ok=True)

if not os.path.ismount(data_dir):
    print(
        f"\nERROR: {data_dir} is not a persistent Docker volume mount.\n\n"
        "Morning News stores its SQLite database, episodes, and uploads under /data.\n"
        "Without a host path or named volume mapped to /data, every image pull starts\n"
        "with an empty database.\n\n"
        "Unraid — Docker UI:\n"
        "  Path mapping: Host /mnt/user/appdata/morning-news → Container /data\n"
        "  Then restart the container.\n\n"
        "Unraid — recommended (docker compose in appdata):\n"
        "  1. Copy docker-compose.unraid.yml and .env to /mnt/user/appdata/morning-news\n"
        "  2. docker compose -f docker-compose.unraid.yml pull\n"
        "  3. docker compose -f docker-compose.unraid.yml up -d\n\n",
        file=sys.stderr,
    )
    sys.exit(1)

mount_source = None
try:
    with open("/proc/self/mountinfo", encoding="utf-8") as mount_info:
        for line in mount_info:
            parts = line.split()
            if len(parts) > 4 and parts[4] == data_dir:
                dash = line.find(" - ")
                if dash >= 0:
                    mount_source = line[dash + 3 :].split()[1]
                break
except OSError:
    pass

if mount_source:
    print(f"Using persistent storage at {data_dir} (mount source: {mount_source})")
else:
    print(f"Using persistent storage at {data_dir}")
PY

exec "$@"
