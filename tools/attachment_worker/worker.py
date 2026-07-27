from __future__ import annotations

import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.attachment_worker_runtime import (  # noqa: E402
    process_worker_request,
    worker_error_response,
)


def main() -> int:
    raw = sys.stdin.readline()
    attachment_id = ""
    try:
        request = json.loads(raw)
        if not isinstance(request, dict):
            raise ValueError("worker request must be an object")
        attachment_id = str(request.get("attachmentId") or "")
        response = process_worker_request(request)
    except Exception as exc:
        response = worker_error_response(attachment_id, exc)
    sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
    sys.stdout.flush()
    return 0 if response.get("status") == "ready" else 2


if __name__ == "__main__":
    raise SystemExit(main())
