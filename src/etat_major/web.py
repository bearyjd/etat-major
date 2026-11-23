"""Optional local HTTP entry point for the read-only Planning snapshot."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from argparse import ArgumentParser, Namespace

    from fastapi import FastAPI

    from etat_major.planning_view import PlanningView

_HEADERS = {
    "Cache-Control": "no-store",
    "Content-Security-Policy": (
        "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
}


def serve_parser(parser: ArgumentParser) -> None:
    parser.add_argument("--workspace", type=Path, required=True, help="intent workspace directory")
    parser.add_argument("--project", required=True, help="project identifier in the workspace")
    parser.add_argument("--port", type=int, default=8765, help="loopback port (default: 8765)")
    for flag, description in (
        ("components", "component YAML (defaults to workspace/components/PROJECT.yaml)"),
        ("graph", "recorded Floorplan graph"),
        ("trail", "recorded Trail wiring"),
        ("repo", "local repository for Git evidence"),
        ("prs", "recorded pull request JSON"),
        ("releases", "recorded release JSON"),
    ):
        parser.add_argument(f"--{flag}", type=Path, help=description)


def create_app(view: PlanningView) -> FastAPI:
    from fastapi import FastAPI
    from fastapi.middleware.trustedhost import TrustedHostMiddleware
    from fastapi.responses import HTMLResponse, JSONResponse

    from etat_major.planning_html import render

    app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None, redirect_slashes=False)
    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=("127.0.0.1", "localhost"), www_redirect=False
    )
    html = HTMLResponse(render(view), headers=_HEADERS)
    data = JSONResponse(asdict(view), headers=_HEADERS)

    @app.get("/")
    def planning():
        return html

    @app.get("/project.json")
    def project():
        return data

    return app


def run_serve(args: Namespace) -> int:
    from etat_major.planning_view import PlanningInputs, load_planning_view
    from etat_major.taskfile import TaskFileError

    if not 1 <= args.port <= 65535:
        raise TaskFileError(Path("serve"), "port", "expected a port from 1 to 65535")
    view = load_planning_view(
        PlanningInputs(
            args.workspace,
            args.project,
            args.components,
            args.graph,
            args.trail,
            args.repo,
            args.prs,
            args.releases,
        )
    )
    try:
        import uvicorn

        app = create_app(view)
    except ModuleNotFoundError as exc:
        if exc.name not in {None, "fastapi", "uvicorn"}:
            raise
        raise TaskFileError(
            Path("serve"), "web", "install etat-major[web] to serve Planning"
        ) from None
    uvicorn.run(app, host="127.0.0.1", port=args.port, proxy_headers=False, access_log=False)
    return 0
