"""Launch the local Pixorra API for one project folder.

Usage: python -m server <project-folder> [--schema PROJECT-RELATIVE-PATH]
       [--port 8799]
"""

from __future__ import annotations

import argparse

from .app import create_app


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="pixorra-server")
    parser.add_argument("folder")
    parser.add_argument("--schema", default=None)
    parser.add_argument("--port", type=int, default=8799)
    args = parser.parse_args(argv)

    import uvicorn

    app = create_app(folder=args.folder, schema=args.schema)
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
