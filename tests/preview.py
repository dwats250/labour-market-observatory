"""Build a clearly labelled SAMPLE preview from the fake WDS, for layout checks.

    python3 -m tests.preview [OUT_DIR]      (default: ./preview, git-ignored)

Includes one flagged (E) value and one suppressed value so their rendering can
be inspected. Never deploy this output.
"""
import shutil
import sys
import tempfile
from pathlib import Path

from src import build, collect
from tests.fake_wds import FakeWDS

ROOT = Path(__file__).resolve().parent.parent


def main():
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "preview"
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        (tmp / "config").mkdir()
        shutil.copy(ROOT / "config" / "series.json", tmp / "config" / "series.json")
        fake = FakeWDS()
        fake.overrides[(14100441, "3.3.0.0.0.0.0.0.0.0", "2025-10-01")] = {"statusCode": 4}
        fake.overrides[(14100462, "3.7.1.1.0.0.0.0.0.0", "2026-02-01")] = {"value": None, "statusCode": 3}
        collect.run(tmp, fetch=fake)
        path = build.build(ROOT, tmp / "data", out, sample=True)
    print(f"sample preview: {path}")


if __name__ == "__main__":
    main()
