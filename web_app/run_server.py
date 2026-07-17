from __future__ import annotations

import os

import uvicorn


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        app_dir=os.path.dirname(__file__),
        host=os.environ.get("CNT_HOST", "0.0.0.0"),
        port=int(os.environ.get("CNT_PORT", "8000")),
        reload=False,
    )
