from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


WEB_APP_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = WEB_APP_DIR.parent


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    database_path: Path
    import_dir: Path
    export_dir: Path
    frontend_dist: Path
    max_upload_bytes: int = 50 * 1024 * 1024
    max_rows: int = 100_000
    temporary_ttl_hours: int = 24
    allowed_extensions: tuple[str, ...] = (".xlsx", ".xlsm", ".xls", ".ods", ".csv", ".tsv", ".txt")
    complete_day_lookback: int = 14
    complete_day_min_history: int = 7
    complete_day_min_coverage: float = 0.90
    yield_delta_warning: float = 5.0
    freshness_warning_days: int = 2
    allowed_origins: tuple[str, ...] = ()
    api_token: str | None = None
    auth_users_b64: str | None = None
    auth_secret: str | None = None
    auth_token_ttl_seconds: int = 12 * 60 * 60

    def ensure_directories(self) -> None:
        for path in (self.data_dir, self.import_dir, self.export_dir):
            path.mkdir(parents=True, exist_ok=True)


def build_settings(data_dir: str | Path | None = None) -> Settings:
    configured = data_dir or os.environ.get("CNT_DATA_DIR")
    root = Path(configured).expanduser().resolve() if configured else (WEB_APP_DIR / "data").resolve()
    allowed_origins = tuple(
        origin.strip().rstrip("/")
        for origin in os.environ.get("CNT_ALLOWED_ORIGINS", "").split(",")
        if origin.strip()
    )
    settings = Settings(
        data_dir=root,
        database_path=root / "cnt_analysis.db",
        import_dir=root / "imports",
        export_dir=root / "exports",
        frontend_dist=WEB_APP_DIR / "frontend" / "dist",
        allowed_origins=allowed_origins,
        api_token=os.environ.get("CNT_API_TOKEN") or None,
        auth_users_b64=os.environ.get("CNT_AUTH_USERS_B64") or None,
        auth_secret=os.environ.get("CNT_AUTH_SECRET") or None,
        auth_token_ttl_seconds=_bounded_int(
            os.environ.get("CNT_AUTH_TOKEN_TTL_SECONDS"),
            default=12 * 60 * 60,
            minimum=5 * 60,
            maximum=7 * 24 * 60 * 60,
        ),
    )
    settings.ensure_directories()
    return settings


def _bounded_int(value: str | None, *, default: int, minimum: int, maximum: int) -> int:
    if value is None:
        return default
    try:
        parsed = int(value)
    except ValueError:
        return default
    return min(max(parsed, minimum), maximum)
