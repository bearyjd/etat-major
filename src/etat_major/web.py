"""Optional local HTTP entry point for the read-only Planning snapshot."""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, fields, replace
from datetime import UTC, datetime
from pathlib import Path
from secrets import compare_digest, token_urlsafe
from threading import Lock
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from argparse import ArgumentParser, Namespace
    from collections.abc import Callable

    from fastapi import FastAPI
    from fastapi.responses import HTMLResponse, JSONResponse

    from etat_major.planning_view import PlanningInputs, PlanningView

_HEADERS = {
    "Cache-Control": "no-store",
    "Content-Security-Policy": (
        "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
}
_REFRESH_HEADERS = {**_HEADERS, "Referrer-Policy": "no-referrer"}


def serve_parser(parser: ArgumentParser) -> None:
    parser.add_argument("--workspace", type=Path, required=True, help="intent workspace directory")
    parser.add_argument("--project", required=True, help="project identifier in the workspace")
    parser.add_argument("--codeman-origin", help="trusted HTTPS origin for session context")
    parser.add_argument("--port", type=int, default=8765, help="loopback port (default: 8765)")
    for artifact in ("source", "floorplan", "trail"):
        parser.add_argument(
            f"--{artifact}-revision", help=f"trusted {artifact} snapshot commit SHA"
        )
    for flag, description in (
        ("immutable-source", "immutable source snapshot directory for excerpts"),
        ("components", "component YAML (defaults to workspace/components/PROJECT.yaml)"),
        ("graph", "recorded Floorplan graph"),
        ("trail", "recorded Trail wiring"),
        ("repo", "local repository for Git evidence"),
        ("prs", "recorded pull request JSON"),
        ("releases", "recorded release JSON"),
        ("meute", "recorded Meute snapshot YAML"),
        ("manual-review", "recorded manual Anthropic API review YAML"),
        ("execution-links", "recorded task execution links YAML"),
    ):
        parser.add_argument(f"--{flag}", type=Path, help=description)


def _json_snapshot(view: PlanningView) -> JSONResponse:
    from fastapi.responses import JSONResponse

    payload = asdict(replace(view, _refresh_diagnostics=None, _understand=None))
    payload.pop("_refresh_diagnostics")
    payload.pop("_understand")
    for field in ("meute", "manual_review", "execution_links"):
        if payload[field] is None:
            payload.pop(field)
    return JSONResponse(payload, headers=_HEADERS)


def _render_snapshot(
    view: PlanningView,
    *,
    timestamp: str | None,
    message: str,
    planning_origin: str | None,
    token: str | None,
) -> tuple[HTMLResponse, HTMLResponse, JSONResponse]:
    from fastapi.responses import HTMLResponse

    from etat_major.planning_html import SnapshotStatus, render, render_fleet

    status = SnapshotStatus(timestamp, message, token) if timestamp and token else None
    headers = _REFRESH_HEADERS if status is not None else _HEADERS
    return (
        HTMLResponse(render(view, status=status, planning_origin=planning_origin), headers=headers),
        HTMLResponse(render_fleet(view, status=status), headers=headers),
        _json_snapshot(view),
    )


def _refresh_failure(previous: PlanningView, candidate: PlanningView | None) -> str | None:
    if candidate is None:
        return "The configured project could not be loaded."
    old_invalid = {source.label for source in previous.sources if source.status == "invalid"}
    if any(
        source.status == "invalid" and source.label not in old_invalid
        for source in candidate.sources
    ):
        return "A configured source became invalid."
    before, after = previous._refresh_diagnostics, candidate._refresh_diagnostics
    if before is not None and after is not None:
        has_errors = after.adds_errors(before)
    else:
        has_errors = bool(
            Counter(issue for issue in candidate.issues if issue.severity == "error")
            - Counter(issue for issue in previous.issues if issue.severity == "error")
        )
    return "New record errors were found." if has_errors else None


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class _Snapshots:
    def __init__(
        self, view: PlanningView, reload: Callable[[], PlanningView] | None, origin: str | None
    ) -> None:
        self.view = view
        self.origin = origin
        self.lock = Lock()
        self.timestamp = _now() if reload is not None else None
        self.token = token_urlsafe(24) if reload is not None else None
        self.responses = self._render("Snapshot loaded")

    def _render(self, message: str) -> tuple[HTMLResponse, HTMLResponse, JSONResponse]:
        return _render_snapshot(
            self.view,
            timestamp=self.timestamp,
            message=message,
            planning_origin=self.origin,
            token=self.token,
        )

    def permits(self, token: str) -> bool:
        return self.token is not None and token.isascii() and compare_digest(self.token, token)

    def update(
        self, reload: Callable[[], PlanningView]
    ) -> tuple[HTMLResponse, HTMLResponse, JSONResponse]:
        from etat_major.taskfile import TaskFileError

        with self.lock:
            try:
                candidate = reload()
            except TaskFileError:
                candidate = None
            if (reason := _refresh_failure(self.view, candidate)) is not None:
                self.responses = self._render(
                    f"Update unavailable. Showing the previous snapshot. {reason}"
                )
            elif candidate is not None:
                timestamp = _now()
                responses = _render_snapshot(
                    candidate,
                    timestamp=timestamp,
                    message="Snapshot updated",
                    planning_origin=self.origin,
                    token=self.token,
                )
                self.view, self.timestamp, self.responses = candidate, timestamp, responses
            return self.responses


def create_app(
    view: PlanningView,
    *,
    reload: Callable[[], PlanningView] | None = None,
    planning_origin: str | None = None,
) -> FastAPI:
    from fastapi import FastAPI, Response
    from fastapi.middleware.trustedhost import TrustedHostMiddleware

    app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None, redirect_slashes=False)
    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=("127.0.0.1", "localhost"), www_redirect=False
    )
    snapshots = _Snapshots(view, reload, planning_origin)

    @app.get("/")
    @app.get("/planning")
    def planning():
        return snapshots.responses[0]

    @app.get("/fleet")
    def fleet():
        return snapshots.responses[1]

    from etat_major.understand_html import register

    register(app, lambda: snapshots.view._understand, _HEADERS)

    @app.get("/project.json")
    def project():
        return snapshots.responses[2]

    if reload is not None:

        @app.get("/refresh")
        def refresh_planning(token: str = ""):
            if not snapshots.permits(token):
                return Response(status_code=403, headers=_REFRESH_HEADERS)
            return snapshots.update(reload)[0]

        @app.get("/fleet-refresh")
        def refresh_fleet(token: str = ""):
            if not snapshots.permits(token):
                return Response(status_code=403, headers=_REFRESH_HEADERS)
            return snapshots.update(reload)[1]

    return app


def _startup_paths(inputs: PlanningInputs) -> PlanningInputs:
    return replace(
        inputs,
        **{
            field.name: value.absolute()
            for field in fields(inputs)
            if isinstance(value := getattr(inputs, field.name), Path)
        },
    )


def run_serve(args: Namespace) -> int:
    from etat_major.planning_view import PlanningInputs, load_planning_view
    from etat_major.taskfile import TaskFileError

    if not 1 <= args.port <= 65535:
        raise TaskFileError(Path("serve"), "port", "expected a port from 1 to 65535")
    inputs = _startup_paths(
        PlanningInputs(
            args.workspace,
            args.project,
            args.components,
            args.graph,
            args.trail,
            args.repo,
            args.prs,
            args.releases,
            args.meute,
            args.manual_review,
            immutable_source=args.immutable_source,
            source_revision=args.source_revision,
            floorplan_revision=args.floorplan_revision,
            trail_revision=args.trail_revision,
            execution_links=args.execution_links,
            codeman_origin=args.codeman_origin,
        )
    )
    view = load_planning_view(inputs)
    try:
        import uvicorn

        app = create_app(
            view,
            reload=lambda: load_planning_view(inputs),
            planning_origin=f"http://127.0.0.1:{args.port}",
        )
    except ModuleNotFoundError as exc:
        if exc.name not in {None, "fastapi", "uvicorn"}:
            raise
        raise TaskFileError(
            Path("serve"), "web", "install etat-major[web] to serve Planning"
        ) from None
    uvicorn.run(app, host="127.0.0.1", port=args.port, proxy_headers=False, access_log=False)
    return 0
