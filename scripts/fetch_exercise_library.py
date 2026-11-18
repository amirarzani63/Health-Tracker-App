"""Download the free-exercise-db photo library into app/static/exlib.

free-exercise-db (github.com/yuhonas/free-exercise-db) is released into the public domain
(Unlicense): ~800 exercises, each with real photos of the start and finish position,
muscles worked and instructions. It is downloaded once when the app is built (the running
app never contacts it). If the download fails the app still works, without photos.
"""

import io
import json
import shutil
import sys
import tarfile
import urllib.request
from pathlib import Path

URL = "https://codeload.github.com/yuhonas/free-exercise-db/tar.gz/refs/heads/main"
DEST = Path(__file__).resolve().parent.parent / "app" / "static" / "exlib"
MAX_BYTES = 400 * 1024 * 1024


def extract(data: bytes, dest: Path) -> int:
    """Copy exercises.json and the exercise photos out of the repository archive."""
    tmp = dest.with_name(dest.name + ".tmp")
    if tmp.exists():
        shutil.rmtree(tmp)
    (tmp / "img").mkdir(parents=True)
    exercises, photos = None, 0
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        for m in tar.getmembers():
            if not m.isfile():
                continue
            parts = m.name.split("/")[1:]  # drop the "free-exercise-db-main/" prefix
            if parts == ["dist", "exercises.json"]:
                exercises = json.loads(tar.extractfile(m).read())
            elif len(parts) == 3 and parts[0] == "exercises" and parts[2].lower().endswith((".jpg", ".jpeg", ".png")):
                folder, file = parts[1], parts[2]
                if "/" in folder or ".." in folder or ".." in file:
                    continue
                out = tmp / "img" / folder
                out.mkdir(exist_ok=True)
                (out / file).write_bytes(tar.extractfile(m).read())
                photos += 1
            elif len(parts) == 1 and parts[0] in ("LICENSE", "LICENSE.md"):
                (tmp / "LICENSE.md").write_bytes(tar.extractfile(m).read())
    if not isinstance(exercises, list) or not exercises:
        shutil.rmtree(tmp)
        raise ValueError("exercises.json missing from the archive")
    (tmp / "exercises.json").write_text(json.dumps(exercises))
    (tmp / "SOURCE").write_text("free-exercise-db\n")
    if dest.exists():
        shutil.rmtree(dest)
    tmp.rename(dest)
    return photos


def main() -> int:
    if (DEST / "SOURCE").exists() and (DEST / "SOURCE").read_text().strip() == "free-exercise-db":
        print("exercise photo library already present")
        return 0
    try:
        with urllib.request.urlopen(URL, timeout=300) as r:
            data = r.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise ValueError("archive unexpectedly large")
        photos = extract(data, DEST)
    except Exception as e:  # noqa: BLE001 - optional asset; the app works without photos
        print(f"warning: couldn't fetch the exercise photo library ({e}); continuing without photos")
        return 0
    print(f"exercise photo library: {photos} photos")
    return 0


if __name__ == "__main__":
    sys.exit(main())
