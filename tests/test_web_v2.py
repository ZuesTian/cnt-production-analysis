from __future__ import annotations

import csv
import base64
import io
import json
import sys
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

import pytest
import pandas as pd
from fastapi.testclient import TestClient
from sqlalchemy import select


ROOT = Path(__file__).resolve().parents[1]
WEB_APP = ROOT / "web_app"
sys.path.insert(0, str(WEB_APP))
sys.path.insert(0, str(ROOT))

from main import create_app
from auth import (
    AuthConfigurationError,
    InvalidSessionError,
    LoginRateLimiter,
    hash_password,
    verify_password,
)
from models import Dataset, ExportArtifact, ShiftRecord, utcnow
from routes.api_v1 import _resolve_content_extension
from services.import_service import _record_classes, _similar_operator_pairs


SOURCE_COLUMNS = [
    "日期",
    "班组",
    "炉号",
    "生产时间",
    "设备故障影响时间",
    "停机清理空烧",
    "产量",
    "小时产能",
]


@pytest.fixture(autouse=True)
def isolate_runtime_auth_environment(monkeypatch):
    for name in (
        "CNT_API_TOKEN",
        "CNT_AUTH_USERS_B64",
        "CNT_AUTH_SECRET",
        "CNT_AUTH_TOKEN_TTL_SECONDS",
    ):
        monkeypatch.delenv(name, raising=False)


def test_similar_operator_names_are_only_reported_as_review_hints() -> None:
    pairs = _similar_operator_pairs(pd.Series(["张晓明", "张小明", "王强", "王刚"]))

    assert ["张小明", "张晓明"] in pairs
    assert ["王刚", "王强"] not in pairs


def test_incomplete_production_rows_never_leave_nullable_validity_flags() -> None:
    frame = pd.DataFrame(
        {
            "反应时间": pd.Series([pd.NA, 8.0, pd.NA], dtype="Float64"),
            "产量": pd.Series([1075.0, 800.0, pd.NA], dtype="Float64"),
            "故障时间": [0.0, 0.0, 0.0],
            "空烧时间": [0.0, 0.0, 0.0],
        }
    )

    classes, valid, _masks = _record_classes(frame)

    assert classes.tolist() == ["incomplete_production", "production", "empty"]
    assert valid.isna().sum() == 0
    assert valid.tolist() == [True, True, False]


def test_remote_api_requires_bearer_token_and_supports_cors(tmp_path: Path, monkeypatch) -> None:
    origin = "https://zuestian.github.io"
    monkeypatch.setenv("CNT_API_TOKEN", "deployment-secret")
    monkeypatch.setenv("CNT_ALLOWED_ORIGINS", origin)
    app = create_app(tmp_path / "runtime", serve_frontend=False)

    with TestClient(app) as client:
        health = client.get("/api/v1/health")
        assert health.status_code == 200

        unauthorized = client.get("/api/v1/datasets", headers={"Origin": origin})
        assert unauthorized.status_code == 401
        assert unauthorized.json()["code"] == "AUTH_REQUIRED"
        assert unauthorized.headers["access-control-allow-origin"] == origin

        preflight = client.options(
            "/api/v1/datasets",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "authorization,x-cnt-workspace",
            },
        )
        assert preflight.status_code == 200
        assert preflight.headers["access-control-allow-origin"] == origin

        authorized = client.get(
            "/api/v1/auth/check",
            headers={
                "Origin": origin,
                "Authorization": "Bearer deployment-secret",
                "X-CNT-Workspace": "browserworkspace123456789012",
            },
        )
        assert authorized.status_code == 200
        assert authorized.json() == {
            "status": "ok",
            "user": {"username": "api-token", "display_name": "访问密钥用户"},
        }


def _auth_users_config(users: list[tuple[str, str, str]]) -> str:
    payload = [
        {
            "username": username,
            "display_name": display_name,
            "password_hash": hash_password(password, iterations=100_000),
        }
        for username, display_name, password in users
    ]
    return base64.urlsafe_b64encode(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).decode("ascii")


def test_account_login_issues_signed_sessions_for_all_configured_users(
    tmp_path: Path,
    monkeypatch,
) -> None:
    users = [
        ("owner", "负责人", "owner-password"),
        ("operator", "操作员", "operator-password"),
        ("shared", "共用账号", "shared-password"),
    ]
    monkeypatch.setenv("CNT_API_TOKEN", "legacy-token-must-not-bypass-account-login")
    monkeypatch.setenv("CNT_AUTH_USERS_B64", _auth_users_config(users))
    monkeypatch.setenv("CNT_AUTH_SECRET", "test-session-signing-secret-that-is-long-enough")
    monkeypatch.setenv("CNT_AUTH_TOKEN_TTL_SECONDS", "3600")
    app = create_app(tmp_path / "runtime", serve_frontend=False)

    with TestClient(app) as client:
        assert client.get("/api/v1/health").status_code == 200
        unauthorized = client.get("/api/v1/datasets")
        assert unauthorized.status_code == 401
        assert unauthorized.json()["code"] == "AUTH_REQUIRED"
        legacy = client.get(
            "/api/v1/datasets",
            headers={"Authorization": "Bearer legacy-token-must-not-bypass-account-login"},
        )
        assert legacy.status_code == 401
        assert legacy.json()["code"] == "AUTH_INVALID"

        wrong = client.post(
            "/api/v1/auth/login",
            json={"username": "owner", "password": "wrong-password"},
        )
        assert wrong.status_code == 401
        assert wrong.json() == {
            "code": "INVALID_CREDENTIALS",
            "message": "账号或密码错误",
            "details": None,
        }

        tokens: dict[str, str] = {}
        for username, display_name, password in users:
            login = client.post(
                "/api/v1/auth/login",
                json={"username": username, "password": password},
            )
            assert login.status_code == 200, login.text
            body = login.json()
            assert body["token_type"] == "bearer"
            assert body["expires_in"] == 3600
            assert body["user"] == {"username": username, "display_name": display_name}
            assert "password" not in json.dumps(body)
            assert login.headers["cache-control"] == "no-store"
            tokens[username] = body["access_token"]

        headers = {"Authorization": f"Bearer {tokens['operator']}"}
        me = client.get("/api/v1/auth/me", headers=headers)
        assert me.status_code == 200
        assert me.json() == {"username": "operator", "display_name": "操作员"}
        check = client.get("/api/v1/auth/check", headers=headers)
        assert check.json()["user"] == me.json()
        assert client.get("/api/v1/datasets", headers=headers).status_code == 200
        assert client.post("/api/v1/auth/logout", headers=headers).json() == {"status": "ok"}

        tampered = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {tokens['owner']}x"},
        )
        assert tampered.status_code == 401
        assert tampered.json()["code"] == "AUTH_INVALID"

    manager = app.state.auth_manager
    assert manager is not None
    owner = manager.users["owner"]
    expired_token, _ = manager.issue_token(owner, now=1_000)
    with pytest.raises(InvalidSessionError):
        manager.verify_token(expired_token, now=4_600)


def test_password_hash_and_login_failure_rate_limit(tmp_path: Path, monkeypatch) -> None:
    encoded = hash_password("correct horse", iterations=100_000)
    assert verify_password("correct horse", encoded)
    assert not verify_password("wrong horse", encoded)

    monkeypatch.setenv(
        "CNT_AUTH_USERS_B64",
        _auth_users_config([("limited", "限速测试", "correct-password")]),
    )
    monkeypatch.setenv("CNT_AUTH_SECRET", "another-test-session-secret-that-is-long-enough")
    app = create_app(tmp_path / "runtime", serve_frontend=False)
    app.state.auth_manager.login_limiter = LoginRateLimiter(attempts=2, window_seconds=600)

    with TestClient(app) as client:
        for _ in range(2):
            response = client.post(
                "/api/v1/auth/login",
                json={"username": "limited", "password": "incorrect"},
            )
            assert response.status_code == 401
        limited = client.post(
            "/api/v1/auth/login",
            json={"username": "limited", "password": "correct-password"},
        )
        assert limited.status_code == 429
        assert limited.json()["code"] == "LOGIN_RATE_LIMITED"


def test_partial_account_auth_configuration_fails_closed(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv(
        "CNT_AUTH_USERS_B64",
        _auth_users_config([("member", "成员", "password")]),
    )
    with pytest.raises(AuthConfigurationError):
        create_app(tmp_path / "runtime", serve_frontend=False)


def source_rows(output_offset: float = 0) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    start = date(2026, 1, 1)
    for day_index in range(10):
        day = (start + timedelta(days=day_index)).isoformat()
        rows.extend(
            [
                {
                    "日期": day,
                    "班组": "白班 张三",
                    "炉号": "E01",
                    "生产时间": 2,
                    "设备故障影响时间": 0,
                    "停机清理空烧": 0,
                    "产量": 100 + output_offset,
                    "小时产能": 50,
                },
                {
                    "日期": day,
                    "班组": "夜班\n李四",
                    "炉号": "E02",
                    "生产时间": 8,
                    "设备故障影响时间": 13 if day_index == 8 else 0,
                    "停机清理空烧": 2 if day_index == 8 else 0,
                    "产量": 800 + output_offset,
                    "小时产能": 100,
                },
                {
                    "日期": day,
                    "班组": "白班王五",
                    "炉号": "11A-01",
                    "生产时间": 5,
                    "设备故障影响时间": 0,
                    "停机清理空烧": 0,
                    "产量": 350 + output_offset,
                    "小时产能": 70,
                },
            ]
        )
        # The latest 11A date contains one row instead of the historical two;
        # it must not be treated as a complete comparison day.
        if day_index < 9:
            rows.append(
                {
                    "日期": day,
                    "班组": "夜班赵六",
                    "炉号": "11A-02",
                    "生产时间": 5,
                    "设备故障影响时间": 0,
                    "停机清理空烧": 0,
                    "产量": 400 + output_offset,
                    "小时产能": 80,
                }
            )
    rows.append(
        {
            "日期": "not-a-date",
            "班组": "白班待核对",
            "炉号": "E99",
            "生产时间": 8,
            "设备故障影响时间": 0,
            "停机清理空烧": 0,
            "产量": 600,
            "小时产能": 75,
        }
    )
    return rows


def csv_bytes(rows: list[dict[str, object]]) -> bytes:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=SOURCE_COLUMNS)
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8-sig")


def spreadsheet_bytes(rows: list[dict[str, object]], engine: str = "openpyxl") -> bytes:
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine=engine) as writer:
        pd.DataFrame(rows).to_excel(writer, sheet_name="L3生产数据", index=False)
    return buffer.getvalue()


def wait_job(client: TestClient, job_id: str, timeout: float = 20) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get(f"/api/v1/jobs/{job_id}")
        assert response.status_code == 200, response.text
        job = response.json()
        if job["status"] in {"completed", "failed", "cancelled"}:
            return job
        time.sleep(0.05)
    raise AssertionError("background job timed out")


def import_dataset(client: TestClient, rows: list[dict[str, object]], kind: str = "temporary", filename: str = "sample.csv") -> tuple[str, dict]:
    response = client.post(
        "/api/v1/datasets/imports",
        files={"file": (filename, csv_bytes(rows), "text/csv")},
        data={"kind": kind, "name": f"test-{time.time_ns()}"},
    )
    assert response.status_code == 202, response.text
    payload = response.json()
    job = wait_job(client, payload["job_id"])
    assert job["status"] == "completed", job.get("error_detail")
    return payload["dataset_id"], job


def test_file_import_accepts_xlsx_xlsm_ods_tsv_and_txt(app_client) -> None:
    _app, client = app_client
    rows = source_rows()
    xlsx = spreadsheet_bytes(rows)
    ods = spreadsheet_bytes(rows, "odf")
    tabular = pd.DataFrame(rows).to_csv(index=False, sep="\t").encode("utf-8-sig")
    pipe = pd.DataFrame(rows).to_csv(index=False, sep="|").encode("gb18030")
    samples = [
        ("production.xlsx", xlsx, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
        ("production.xlsm", xlsx, "application/vnd.ms-excel.sheet.macroEnabled.12"),
        ("production.ods", ods, "application/vnd.oasis.opendocument.spreadsheet"),
        ("production.tsv", tabular, "text/tab-separated-values"),
        ("production.txt", pipe, "text/plain"),
    ]

    for filename, content, content_type in samples:
        accepted = client.post(
            "/api/v1/datasets/imports",
            files={"file": (filename, content, content_type)},
            data={"kind": "temporary", "name": filename},
        )
        assert accepted.status_code == 202, accepted.text
        job = wait_job(client, accepted.json()["job_id"])
        assert job["status"] == "completed", job.get("error_detail")
        quality = client.get(f"/api/v1/datasets/{accepted.json()['dataset_id']}/quality")
        assert quality.status_code == 200
        assert quality.json()["dataset"]["row_count"] > 0


def test_xlxs_alias_is_normalized_to_xlsx_and_still_validated(app_client) -> None:
    app, client = app_client
    accepted = client.post(
        "/api/v1/datasets/imports",
        files={"file": ("现场生产数据.xlxs", spreadsheet_bytes(source_rows()), "application/octet-stream")},
        data={"kind": "temporary", "name": "xlxs 兼容验收"},
    )
    assert accepted.status_code == 202, accepted.text
    payload = accepted.json()
    job = wait_job(client, payload["job_id"])
    assert job["status"] == "completed", job.get("error_detail")
    with app.state.SessionLocal() as session:
        dataset = session.get(Dataset, payload["dataset_id"])
        assert dataset.original_filename == "现场生产数据.xlxs"
        assert Path(dataset.stored_path).suffix == ".xlsx"

    invalid = client.post(
        "/api/v1/datasets/imports",
        files={"file": ("伪装文件.xlxs", b"not an Excel workbook", "application/octet-stream")},
        data={"kind": "temporary"},
    )
    assert invalid.status_code == 415
    assert invalid.json()["code"] == "FILE_FORMAT_MISMATCH"


def test_xlsx_named_legacy_workbook_is_detected_as_xls(tmp_path: Path) -> None:
    legacy = tmp_path / "legacy.xlsx"
    legacy.write_bytes(bytes.fromhex("D0CF11E0A1B11AE1") + b"legacy workbook placeholder")

    assert _resolve_content_extension(legacy, ".xlsx") == ".xls"


def test_paste_import_accepts_excel_clipboard_tsv_and_runs_quality_gate(app_client) -> None:
    app, client = app_client
    content = pd.DataFrame(source_rows()).to_csv(index=False, sep="\t")
    accepted = client.post(
        "/api/v1/datasets/paste-imports",
        json={"kind": "temporary", "name": "七月现场粘贴", "content": content},
    )

    assert accepted.status_code == 202, accepted.text
    payload = accepted.json()
    job = wait_job(client, payload["job_id"])
    assert job["status"] == "completed", job.get("error_detail")
    quality = client.get(f"/api/v1/datasets/{payload['dataset_id']}/quality").json()
    assert quality["dataset"]["name"] == "七月现场粘贴"
    assert quality["dataset"]["row_count"] > 0
    with app.state.SessionLocal() as session:
        dataset = session.get(Dataset, payload["dataset_id"])
        assert dataset.original_filename == "七月现场粘贴.tsv"
        assert Path(dataset.stored_path).suffix == ".tsv"

    invalid = client.post(
        "/api/v1/datasets/paste-imports",
        json={"kind": "temporary", "name": "无效粘贴", "content": "只有一列\n没有分隔符"},
    )
    assert invalid.status_code == 415
    assert invalid.json()["code"] == "FILE_FORMAT_MISMATCH"


def publish_dataset(client: TestClient, dataset_id: str, activate: bool = False) -> dict:
    quality = client.get(f"/api/v1/datasets/{dataset_id}/quality").json()
    high_codes = [item["code"] for item in quality["issues"] if item["severity"] == "high"]
    response = client.post(
        f"/api/v1/datasets/{dataset_id}/{'activate' if activate else 'publish'}",
        json={
            "confirm": True,
            "complete_dates": quality["dataset"]["complete_dates"],
            "acknowledged_issue_codes": high_codes,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture()
def app_client(tmp_path: Path):
    app = create_app(tmp_path / "runtime", serve_frontend=False)
    with TestClient(app) as client:
        yield app, client


def test_import_quality_dual_grain_and_weighted_overview(app_client) -> None:
    _app, client = app_client
    dataset_id, import_job = import_dataset(client, source_rows())

    job_batch = client.post("/api/v1/jobs", json={"ids": [import_job["id"]]})
    assert job_batch.status_code == 200
    assert [item["id"] for item in job_batch.json()] == [import_job["id"]]
    assert len(client.get("/api/v1/datasets?limit=1&offset=0").json()) == 1
    assert client.get("/api/v1/datasets?limit=1&offset=1").json() == []

    quality_response = client.get(f"/api/v1/datasets/{dataset_id}/quality")
    assert quality_response.status_code == 200
    quality = quality_response.json()
    assert quality["dataset"]["row_count"] == 39
    assert quality["dataset"]["complete_dates"]["11A"] == "2026-01-09"
    assert any(issue["code"] == "PARTIAL_LATEST_DAY" for issue in quality["issues"])
    assert any(issue["code"] == "INVALID_DATE" for issue in quality["issues"])

    overview = client.get(f"/api/v1/dashboard/overview?dataset_id={dataset_id}").json()
    l3 = next(item for item in overview["line_snapshots"] if item["production_line"] == "L3")
    kpis = {item["key"]: item for item in l3["kpis"]}
    assert kpis["total_output"]["value"] == pytest.approx(900)
    assert kpis["weighted_yield"]["value"] == pytest.approx(90)  # not simple mean 75
    assert kpis["fault_hours"]["value"] == pytest.approx(0)
    assert overview["common_comparison_date"] == "2026-01-09"

    shift = client.get(f"/api/v1/dashboard/trends?dataset_id={dataset_id}&grain=shift").json()
    furnace_day = client.get(f"/api/v1/dashboard/trends?dataset_id={dataset_id}&grain=furnace_day").json()
    assert len(shift["rows"]) > len(furnace_day["rows"])
    assert all("shift_name" in row for row in shift["rows"])
    assert all("shift_name" not in row for row in furnace_day["rows"])
    jan9_l3 = [
        row for row in shift["rows"]
        if row["production_date"] == "2026-01-09" and row["production_line"] == "L3"
    ]
    assert sum(row["clean_empty_burn_hours"] for row in jan9_l3) == pytest.approx(2)  # one source field, not doubled

    shift_detail = client.get(f"/api/v1/furnaces/E01?dataset_id={dataset_id}&grain=shift").json()
    day_detail = client.get(f"/api/v1/furnaces/E01?dataset_id={dataset_id}&grain=furnace_day").json()
    assert "shift_name" in shift_detail["rows"][0]
    assert "shift_name" not in day_detail["rows"][0]

    fault_diagnostic = client.get(f"/api/v1/diagnostics/faults?dataset_id={dataset_id}&grain=shift").json()
    distribution = client.get(f"/api/v1/diagnostics/distribution?dataset_id={dataset_id}&grain=furnace_day").json()
    assert fault_diagnostic["grain"] == "furnace_day"
    assert distribution["grain"] == "shift"


def test_overview_counts_serious_alerts_after_furnace_day_aggregation(app_client) -> None:
    _app, client = app_client
    rows = source_rows()
    latest_l3 = [
        row for row in rows
        if row["日期"] == "2026-01-10" and str(row["炉号"]).startswith("E")
    ]
    for row in latest_l3:
        row["炉号"] = "E01"
        row["设备故障影响时间"] = 7
    dataset_id, _job = import_dataset(client, rows)

    overview = client.get(f"/api/v1/dashboard/overview?dataset_id={dataset_id}").json()
    l3 = next(item for item in overview["line_snapshots"] if item["production_line"] == "L3")

    assert l3["serious_alerts"] == 1


def test_publish_replace_rollback_and_fault_warning_export(app_client) -> None:
    _app, client = app_client
    first_id, _ = import_dataset(client, source_rows(), "shared", "first.csv")
    publish_dataset(client, first_id)
    first_output = next(
        item for item in client.get("/api/v1/dashboard/overview").json()["line_snapshots"]
        if item["production_line"] == "L3"
    )["kpis"][0]["value"]

    second_id, _ = import_dataset(client, source_rows(10), "shared", "second.csv")
    publish_dataset(client, second_id)
    listed = client.get("/api/v1/datasets").json()
    assert next(item for item in listed if item["id"] == first_id)["status"] == "archived"
    assert next(item for item in listed if item["id"] == second_id)["status"] == "published"

    publish_dataset(client, first_id, activate=True)
    restored_output = next(
        item for item in client.get("/api/v1/dashboard/overview").json()["line_snapshots"]
        if item["production_line"] == "L3"
    )["kpis"][0]["value"]
    assert restored_output == first_output

    accepted = client.post("/api/v1/exports", json={"dataset_id": first_id, "report_type": "fault_warning"})
    assert accepted.status_code == 202
    job = wait_job(client, accepted.json()["job_id"], timeout=30)
    assert job["status"] == "completed", job.get("error_detail")
    download = client.get(f"/api/v1/exports/{job['result']['export_id']}/download")
    assert download.status_code == 200
    assert download.content.startswith(b"PK")


def test_temporary_dataset_isolated_by_http_only_workspace_cookie(tmp_path: Path) -> None:
    app = create_app(tmp_path / "runtime", serve_frontend=False)
    with TestClient(app) as owner, TestClient(app) as stranger:
        dataset_id, _ = import_dataset(owner, source_rows())
        assert owner.get(f"/api/v1/datasets/{dataset_id}/quality").status_code == 200
        assert stranger.get(f"/api/v1/datasets/{dataset_id}/quality").status_code == 403
        assert dataset_id not in {item["id"] for item in stranger.get("/api/v1/datasets").json()}
        cookie = owner.cookies.get("cnt_workspace")
        assert cookie and len(cookie) >= 24

        accepted = owner.post(
            "/api/v1/exports", json={"dataset_id": dataset_id, "report_type": "daily_summary"}
        )
        export_job = wait_job(owner, accepted.json()["job_id"])
        assert export_job["status"] == "completed"
        export_id = export_job["result"]["export_id"]
        with app.state.SessionLocal() as session:
            dataset = session.get(Dataset, dataset_id)
            source_path = Path(dataset.stored_path)
            dataset.expires_at = utcnow() - timedelta(seconds=1)
            artifact = session.get(ExportArtifact, export_id)
            export_path = Path(artifact.stored_path)
            session.commit()

        owner.get("/api/v1/datasets")  # triggers bounded expiry cleanup
        assert not source_path.exists()
        assert not export_path.exists()
        with app.state.SessionLocal() as session:
            assert session.get(Dataset, dataset_id) is None
            assert session.query(ShiftRecord).filter_by(dataset_id=dataset_id).count() == 0
            assert session.get(ExportArtifact, export_id) is None


def test_upload_limits_signature_and_generated_safe_path(tmp_path: Path) -> None:
    app = create_app(tmp_path / "runtime", serve_frontend=False)
    app.state.settings = replace(app.state.settings, max_upload_bytes=128)
    with TestClient(app) as client:
        too_large = client.post(
            "/api/v1/datasets/imports",
            files={"file": ("large.csv", b"a,b\n" + b"x" * 200, "text/csv")},
            data={"kind": "temporary"},
        )
        assert too_large.status_code == 413
        assert too_large.json()["code"] == "FILE_TOO_LARGE"

    app = create_app(tmp_path / "runtime2", serve_frontend=False)
    with TestClient(app) as client:
        mismatch = client.post(
            "/api/v1/datasets/imports",
            files={"file": ("fake.xlsx", b"not an excel workbook", "application/octet-stream")},
            data={"kind": "temporary"},
        )
        assert mismatch.status_code == 415
        fake_zip = io.BytesIO()
        with zipfile.ZipFile(fake_zip, "w") as archive:
            archive.writestr("unrelated.txt", "not a workbook")
        disguised_zip = client.post(
            "/api/v1/datasets/imports",
            files={"file": ("disguised.xlsx", fake_zip.getvalue(), "application/octet-stream")},
            data={"kind": "temporary"},
        )
        assert disguised_zip.status_code == 415
        assert disguised_zip.json()["code"] == "FILE_FORMAT_MISMATCH"
        dataset_id, _ = import_dataset(client, source_rows(), filename="../../outside.csv")
        with app.state.SessionLocal() as session:
            dataset = session.scalar(select(Dataset).where(Dataset.id == dataset_id))
            stored = Path(dataset.stored_path).resolve()
        assert app.state.settings.import_dir.resolve() in stored.parents
        assert stored.name == f"{dataset_id}.csv"


def test_publish_requires_confirmation_and_high_risk_acknowledgement(app_client) -> None:
    _app, client = app_client
    dataset_id, _ = import_dataset(client, source_rows(), "shared")
    no_confirm = client.post(f"/api/v1/datasets/{dataset_id}/publish", json={"confirm": False})
    assert no_confirm.status_code == 422
    assert no_confirm.json()["code"] == "CONFIRMATION_REQUIRED"
    without_ack = client.post(
        f"/api/v1/datasets/{dataset_id}/publish",
        json={"confirm": True, "complete_dates": {"L3": "2026-01-10", "11A": "2026-01-09"}},
    )
    assert without_ack.status_code == 422
    assert without_ack.json()["code"] == "QUALITY_ACK_REQUIRED"


def test_concurrent_publish_leaves_exactly_one_active_snapshot(app_client) -> None:
    _app, client = app_client
    first_id, _ = import_dataset(client, source_rows(1), "shared", "concurrent-a.csv")
    second_id, _ = import_dataset(client, source_rows(2), "shared", "concurrent-b.csv")

    def payload_for(dataset_id: str) -> dict:
        report = client.get(f"/api/v1/datasets/{dataset_id}/quality").json()
        return {
            "confirm": True,
            "complete_dates": report["dataset"]["complete_dates"],
            "acknowledged_issue_codes": [
                item["code"] for item in report["issues"] if item["severity"] == "high"
            ],
        }

    payloads = {first_id: payload_for(first_id), second_id: payload_for(second_id)}
    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(
            executor.map(
                lambda dataset_id: client.post(
                    f"/api/v1/datasets/{dataset_id}/publish", json=payloads[dataset_id]
                ),
                [first_id, second_id],
            )
        )
    assert [response.status_code for response in responses] == [200, 200]
    datasets = client.get("/api/v1/datasets").json()
    relevant = [item for item in datasets if item["id"] in {first_id, second_id}]
    assert sum(item["status"] == "published" for item in relevant) == 1
    assert sum(item["status"] == "archived" for item in relevant) == 1
