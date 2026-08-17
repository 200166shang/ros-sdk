#!/usr/bin/env bash

set -euo pipefail

if [[ -z "${CONAN_REMOTE_URL:-}" ]]; then
  echo "Conan remote not configured; skipping remote verification"
  exit 0
fi

docker exec ros2 python3 - <<'PY'
import base64
import os
import urllib.error
import urllib.request


remote_url = os.environ["CONAN_REMOTE_URL"].rstrip("/")
username = os.environ.get("CONAN_LOGIN_USERNAME", "")
password = os.environ.get("CONAN_PASSWORD", "")


def request(path: str, authenticated: bool = False) -> None:
    request = urllib.request.Request(remote_url + path)
    if authenticated:
        if not username or not password:
            raise SystemExit("Conan remote credentials are not configured")
        credentials = f"{username}:{password}".encode()
        token = base64.b64encode(credentials).decode()
        request.add_header("Authorization", f"Basic {token}")

    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            if response.status != 200:
                raise SystemExit(f"Conan remote returned HTTP {response.status}")
    except urllib.error.HTTPError as error:
        raise SystemExit(f"Conan remote returned HTTP {error.code}") from error
    except urllib.error.URLError as error:
        raise SystemExit(f"Conan remote is unreachable: {error.reason}") from error


request("/v1/ping")
request("/v2/users/authenticate", authenticated=True)
print("Conan remote reachability and credentials verified")
PY
