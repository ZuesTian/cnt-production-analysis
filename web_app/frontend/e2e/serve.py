"""Run browser tests against an isolated database with a published synthetic dataset."""
import os
import runpy
from pathlib import Path
from tempfile import TemporaryDirectory

import uvicorn
from fastapi.testclient import TestClient

project = Path(__file__).resolve().parents[3]
with TemporaryDirectory(prefix="cnt-e2e-") as data_dir:
    os.environ["CNT_DATA_DIR"] = data_dir
    fixture = runpy.run_path(str(project / "tests/test_web_v2.py"))
    with TestClient(fixture["create_app"]()) as client:
        dataset_id, _ = fixture["import_dataset"](client, fixture["source_rows"](), kind="shared")
        fixture["publish_dataset"](client, dataset_id)
    uvicorn.run(fixture["create_app"](), host="127.0.0.1", port=8765)
