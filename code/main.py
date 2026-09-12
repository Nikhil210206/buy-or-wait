"""Buy or Wait? -- entry point.

    python3 code/main.py              # full run over dataset/requests.csv
    python3 code/main.py --baseline   # emit the schema-valid placeholder output
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import loaders   # noqa: E402
import pipeline  # noqa: E402
import verify    # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "output.csv"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", action="store_true",
                    help="write the placeholder output without running the solver")
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args()

    ds = loaders.load()
    rows = (pipeline.baseline if a.baseline else pipeline.run)(ds, ds.requests)

    errs = verify.verify_rows(ds, rows)
    if errs:
        print(f"verify.py found {len(errs)} contract violations; refusing to write {a.out}",
              file=sys.stderr)
        for e in errs[:40]:
            print("  ", e, file=sys.stderr)
        return 1

    pipeline.write_csv(a.out, rows)
    print(f"wrote {a.out} ({len(rows)} rows, verify clean)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
