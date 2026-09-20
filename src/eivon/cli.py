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
    sub.add_parser("worker", help="Run the durable execution worker")
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


if __name__ == "__main__":
    main()
