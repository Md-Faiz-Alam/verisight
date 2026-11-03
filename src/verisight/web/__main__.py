"""Run the VeriSight website: ``verisight-web`` or ``python -m verisight.web``."""

import argparse


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="verisight-web",
        description="Serve the VeriSight website and REST API.",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)
    try:
        import uvicorn
    except ImportError:
        raise SystemExit(
            'The website needs extra packages: pip install -e ".[web]"'
        ) from None
    print(f"VeriSight is running at http://{args.host}:{args.port}")
    uvicorn.run(
        "verisight.web.app:create_app",
        factory=True,
        host=args.host,
        port=args.port,
        proxy_headers=True,
    )


if __name__ == "__main__":
    main()
