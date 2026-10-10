"""``unheard`` command line: ``unheard serve [--lan] [--port N]``."""

from __future__ import annotations

import argparse
import logging
import os
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="unheard")
    sub = parser.add_subparsers(dest="cmd", required=True)
    serve = sub.add_parser("serve", help="run the API server (serves web/dist if built)")
    serve.add_argument("--host", default=None, help="bind address (default 127.0.0.1)")
    serve.add_argument("--port", type=int, default=None)
    serve.add_argument(
        "--lan", action="store_true", help="bind 0.0.0.0 (requires UNHEARD_API_TOKEN)"
    )
    serve.add_argument("--ssl-certfile", default=None, help="serve HTTPS (e.g. web/certs/dev.pem)")
    serve.add_argument("--ssl-keyfile", default=None, help="private key for --ssl-certfile")
    serve.add_argument("--reload", action="store_true")
    serve.add_argument("--log-level", default="info")
    fetch = sub.add_parser(
        "fetch-model", help="download the audio model weights once (explicit network use)"
    )
    fetch.add_argument("--name", default=None)
    args = parser.parse_args(argv)

    if args.cmd == "fetch-model":
        from huggingface_hub import snapshot_download

        from unheard.config import get_settings

        name = args.name or get_settings().model_name
        path = snapshot_download(name, allow_patterns=["*.json", "*.txt", "*.bin", "*.safetensors"])
        print(f"{name} cached at {path}")
        return 0

    if args.cmd == "serve":
        import uvicorn

        from unheard.config import get_settings

        settings = get_settings()
        host = args.host or ("0.0.0.0" if args.lan else settings.host)
        port = args.port or settings.port
        if host not in ("127.0.0.1", "localhost", "::1") and not settings.api_token:
            print(
                "refusing to bind to a non-loopback address without UNHEARD_API_TOKEN set "
                "(anyone on the network could read or upload recordings)",
                file=sys.stderr,
            )
            return 2
        if bool(args.ssl_certfile) != bool(args.ssl_keyfile):
            print("--ssl-certfile and --ssl-keyfile must be given together", file=sys.stderr)
            return 2
        logging.basicConfig(
            level=args.log_level.upper(), format="%(asctime)s %(levelname)s %(name)s: %(message)s"
        )
        os.environ.setdefault("UNHEARD_HOST", host)
        uvicorn.run(
            "unheard.app:app",
            host=host,
            port=port,
            reload=args.reload,
            log_level=args.log_level,
            ssl_certfile=args.ssl_certfile,
            ssl_keyfile=args.ssl_keyfile,
        )
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
