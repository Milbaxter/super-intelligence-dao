"""`agentdao` console script: serve | seed | invite | generate."""

from __future__ import annotations

import argparse
import json
import sys

from . import config, db


def get_app():
    """Factory for `uvicorn --factory` (used by --reload)."""
    from .app import create_app
    return create_app()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="agentdao", description=f"{config.SITE_NAME} backend")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve", help="run the HTTP server")
    s.add_argument("--port", type=int, default=8787)
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--reload", action="store_true")
    sd = sub.add_parser("seed", help="load seed/*.json, then run the task generator")
    sd.add_argument("--check-sources", action="store_true", help="quote-check seed claims (network) and promote passes to T1")
    sd.add_argument("--reset", action="store_true", help="wipe the database first")
    inv = sub.add_parser("invite", help="create invite codes")
    inv.add_argument("--count", type=int, default=1)
    inv.add_argument("--note", default=None)
    sub.add_parser("generate", help="run the task generator")
    args = p.parse_args(argv)
    settings = config.Settings()

    if args.cmd == "serve":
        import uvicorn
        problems = config.unsafe_for_public_bind(settings, args.host)
        if problems:
            print(f"refusing to serve on {args.host}:", *(f"  - {p}" for p in problems), sep="\n", file=sys.stderr)
            return 2
        if args.reload:
            uvicorn.run("agentdao.cli:get_app", factory=True, host=args.host, port=args.port, reload=True,
                        reload_dirs=[str(config.REPO_ROOT / "server")])
        else:
            from .app import create_app
            uvicorn.run(create_app(settings), host=args.host, port=args.port)
        return 0

    if args.cmd == "seed":
        from . import seed
        from .verify import QuoteChecker

        def progress(claim, res):
            print(f"  [{'PASS' if res['passed'] else res['reason']}] {claim['artifact_id']} / {claim['benchmark_id']}", file=sys.stderr)

        checker = QuoteChecker()
        if args.check_sources:
            print("checking seed claim sources (network)…", file=sys.stderr)
        report = seed.run(settings, reset=args.reset, check=False)
        if args.check_sources:
            conn = db.connect(settings.db_path)
            try:
                report["check_sources"] = seed.check_sources(conn, checker, progress)
                from . import taskgen
                report["taskgen_created"] += len(taskgen.generate(conn))
            finally:
                conn.close()
        print(json.dumps(report, indent=2))
        return 0

    db.init_db(settings.db_path)
    conn = db.connect(settings.db_path)
    try:
        if args.cmd == "invite":
            from .api_admin import create_invites
            for code in create_invites(conn, max(1, min(args.count, 1000)), args.note):
                print(code)
        elif args.cmd == "generate":
            from . import taskgen
            created = taskgen.generate(conn)
            print(json.dumps({"created": created}, indent=2))
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
