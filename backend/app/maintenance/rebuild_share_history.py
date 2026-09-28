"""Resume a bounded TeaJoin historical share-capital repair."""
from __future__ import annotations

import argparse
import json
import sys
import time

import httpx

from app.config import settings
from app.data_providers import custom
from app.services.financial_sync import rebuild_share_history_batch
from app.tickflow.capabilities import CapabilitySet


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch and merge TeaJoin historical share capital with a durable checkpoint.",
    )
    parser.add_argument("--batch-size", type=int, default=5)
    parser.add_argument("--until-complete", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _arguments()
    custom.load_all()
    retries = 0
    while True:
        try:
            result = rebuild_share_history_batch(
                settings.data_dir,
                CapabilitySet(),
                batch_size=args.batch_size,
            )
        except (RuntimeError, ValueError, httpx.HTTPError) as exc:
            transient = isinstance(exc, (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError))
            if isinstance(exc, httpx.HTTPStatusError):
                transient = exc.response.status_code in {429, 500, 502, 503, 504}
            if transient and retries < 3:
                retries += 1
                delay = 5 * 2 ** (retries - 1)
                print(json.dumps({
                    "status": "retry", "error_type": type(exc).__name__,
                    "attempt": retries, "delay_seconds": delay,
                }), file=sys.stderr, flush=True)
                time.sleep(delay)
                continue
            # Exceptions can contain a request URL/token. Only typed failure
            # metadata is safe to persist in the unattended maintenance log.
            print(json.dumps({
                "status": "error", "error_type": type(exc).__name__,
                "retries": retries, "checkpoint_unchanged": True,
            }), file=sys.stderr, flush=True)
            return 1
        retries = 0
        print(json.dumps({"status": "ok", **result}, ensure_ascii=False), flush=True)
        if result["complete"] or not args.until_complete:
            return 0


if __name__ == "__main__":
    raise SystemExit(main())
