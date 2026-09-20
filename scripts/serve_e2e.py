"""Disposable HTTP server for browser acceptance tests; never opens user data."""

from pathlib import Path
from tempfile import TemporaryDirectory

import uvicorn

from eivon.server.app import create_app
from eivon.server.settings import Settings

if __name__ == "__main__":
    with TemporaryDirectory(prefix="eivon-e2e-") as directory:
        app = create_app(
            Settings(
                data_dir=Path(directory),
                database_url="",
                secret_key="",
                extensions=(),
                setup_token="eivon-browser-test",
                allowed_hosts=(),
                secure_cookies=False,
                console_dir=Path(__file__).resolve().parents[1] / "console" / "dist",
                worker_poll_seconds=0.05,
                inline_worker=True,
                testing=True,
            )
        )
        uvicorn.run(app, host="127.0.0.1", port=18787)
