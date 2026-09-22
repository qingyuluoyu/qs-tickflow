"""Resume a bounded TeaJoin historical share-capital repair."""
from __future__ import annotations

import argparse
import json
import sys

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
    while True:
        try:
            result = rebuild_share_history_batch(
                settings.data_dir,
                CapabilitySet(),
                batch_size=args.batch_size,
            )
        except (RuntimeError, ValueError) as exc:
            print(json.dumps({"status": "error", "message": str(exc)}, ensure_ascii=False), file=sys.stderr)
            return 1
        print(json.dumps({"status": "ok", **result}, ensure_ascii=False), flush=True)
        if result["complete"] or not args.until_complete:
            return 0


if __name__ == "__main__":
    raise SystemExit(main())
