"""Command-line entrypoint for local development and self-hosted deployment."""

from __future__ import annotations

import argparse


def main():
    parser = argparse.ArgumentParser(
        prog="eivon", description="Eivon — a home for autonomous intelligence"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="Run the API and management console")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", default=8787, type=int)
    serve.add_argument("--workers", default=1, type=int)
    sub.add_parser("init", help="Initialize the database and local instance secrets")
    sub.add_parser("migrate", help="Apply database migrations")
    worker = sub.add_parser("worker", help="Run the durable execution worker")
    worker.add_argument("--once", action="store_true", help="Claim at most one queued Run")
    args = parser.parse_args()
    if args.command == "serve":
        import uvicorn

        uvicorn.run(
            "eivon.server.app:create_app",
            factory=True,
            host=args.host,
            port=args.port,
            workers=args.workers,
        )
    elif args.command == "init":
        from eivon.server.app import create_app

        app = create_app()
        directory = app.state.settings.data_dir.resolve()
        print(f"Eivon initialized in {directory}")
        print(f"Read {directory / 'setup-token'} to obtain the initial setup token.")
        app.state.database.engine.dispose()
    elif args.command == "migrate":
        from eivon.server.app import create_app
        from eivon.server.migrations import upgrade

        app = create_app()
        version = upgrade(app.state.database)
        print(f"Eivon schema version {version}")
        app.state.database.engine.dispose()
    elif args.command == "worker":
        import asyncio

        from eivon.server.app import create_app

        app = create_app()
        if args.once:
            asyncio.run(app.state.worker.once())
        else:
            try:
                asyncio.run(app.state.worker.loop())
            except KeyboardInterrupt:
                pass
        app.state.database.engine.dispose()


if __name__ == "__main__":
    main()
