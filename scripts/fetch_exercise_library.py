"""Download the RepDB free exercise library (illustrations + exercise data) into app/static/exlib.

Run during the Docker build (and once locally for development). The files are not committed
to the repository: the RepDB license allows in-app use with attribution but not
redistributing the dataset. If the download fails the app still works without pictures.
"""

import base64
import hashlib
import io
import json
import shutil
import sys
import tarfile
import urllib.request
from pathlib import Path

VERSION = "2026.11.1"
URL = f"https://registry.npmjs.org/@repdb/exercises/-/exercises-{VERSION}.tgz"
SHA512 = "uxELzbJS8G0Jyv6wNLpiUz5AIchFbc0mh4CS0eFOKUA1sl7+842MbsZOmhc+5ojSy5nYTS1GEEv3K79T1cPyyw=="
DEST = Path(__file__).resolve().parent.parent / "app" / "static" / "exlib"


def main() -> int:
    if (DEST / "exercises.json").exists() and (DEST / "VERSION").read_text().strip() == VERSION:
        print("exercise library already present")
        return 0
    try:
        data = urllib.request.urlopen(URL, timeout=120).read()
    except Exception as e:  # noqa: BLE001 - optional asset
        print(f"warning: couldn't download the exercise library ({e}); continuing without pictures")
        return 0
    if base64.b64encode(hashlib.sha512(data).digest()).decode() != SHA512:
        print("error: exercise library checksum mismatch", file=sys.stderr)
        return 1
    if DEST.exists():
        shutil.rmtree(DEST)
    (DEST / "img").mkdir(parents=True)
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        for m in tar.getmembers():
            name = m.name.removeprefix("package/")
            if not m.isfile():
                continue
            if name in ("exercises.json", "LICENSE.md", "ATTRIBUTION.md"):
                (DEST / name).write_bytes(tar.extractfile(m).read())
            elif name.startswith("images/flat/") and name.endswith(".webp") and "/" not in name[len("images/flat/"):]:
                (DEST / "img" / Path(name).name).write_bytes(tar.extractfile(m).read())
    json.loads((DEST / "exercises.json").read_text())  # sanity check
    (DEST / "VERSION").write_text(VERSION)
    print(f"exercise library {VERSION}: {len(list((DEST / 'img').iterdir()))} images")
    return 0


if __name__ == "__main__":
    sys.exit(main())
