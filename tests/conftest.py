import os
import tempfile

# Isolate the database before the app is imported.
_tmp = tempfile.mkdtemp()
os.environ["HEALTH_DATA_DIR"] = _tmp
os.environ["GARMIN_AUTO_SYNC_HOURS"] = "0"
os.environ["INSTALL_PRESET_PLAN"] = "0"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture()
def client():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with TestClient(app) as c:
        yield c
