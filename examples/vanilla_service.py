# /// script
# requires-python = ">=3.14"
# dependencies = []
# ///

from __future__ import annotations

import argparse
import json
import os
import queue
import random
import threading
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from demo_service_compute import mandelbrot_ascii, prime_stats


@dataclass(frozen=True, slots=True)
class ServiceConfig:
    host: str
    port: int
    workers: int
    max_recent: int


@dataclass(slots=True)
class RequestContext:
    request_id: int
    method: str
    path: str
    query: dict[str, list[str]]
    started_at: float
    thread: str


@dataclass(frozen=True, slots=True)
class Order:
    id: int
    subtotal: float
    tax_rate: float
    discount: float = 0.0


@dataclass(frozen=True, slots=True)
class Quote:
    order_id: int
    total: float
    breakdown: dict[str, float]


@dataclass(slots=True)
class Job:
    id: int
    kind: str
    params: dict[str, Any]
    created_at: float = field(default_factory=time.time)
    status: str = "queued"
    started_at: float | None = None
    finished_at: float | None = None
    result: Any | None = None
    error: str | None = None


@dataclass(slots=True)
class ServiceState:
    started_at: float = field(default_factory=time.time)
    lock: threading.Lock = field(default_factory=threading.Lock)
    request_seq: int = 0
    job_seq: int = 0
    counts: Counter[str] = field(default_factory=Counter)
    jobs: dict[int, Job] = field(default_factory=dict)
    job_queue: queue.Queue[int] = field(default_factory=queue.Queue)
    stop: threading.Event = field(default_factory=threading.Event)
    recent: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class Response:
    status: int
    headers: dict[str, str]
    body: bytes

    @staticmethod
    def json(payload: Any, *, status: int = 200) -> Response:
        body = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8") + b"\n"
        return Response(
            status=status,
            headers={"Content-Type": "application/json; charset=utf-8"},
            body=body,
        )

    @staticmethod
    def text(payload: str, *, status: int = 200, content_type: str = "text/plain") -> Response:
        body = payload.encode("utf-8") + b"\n"
        return Response(
            status=status,
            headers={"Content-Type": f"{content_type}; charset=utf-8"},
            body=body,
        )


def _as_int(value: str | None, default: int) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _as_float(value: str | None, default: float) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


class VanillaService:
    def __init__(self, *, cfg: ServiceConfig, state: ServiceState | None = None) -> None:
        self.cfg = cfg
        self.state = state or ServiceState()

    def new_context(self, *, method: str, path: str, query: dict[str, list[str]]) -> RequestContext:
        with self.state.lock:
            self.state.request_seq += 1
            request_id = self.state.request_seq
        return RequestContext(
            request_id=request_id,
            method=method,
            path=path,
            query=query,
            started_at=time.time(),
            thread=threading.current_thread().name,
        )

    def record(self, ctx: RequestContext, status: int) -> None:
        elapsed_ms = (time.time() - ctx.started_at) * 1000.0
        item = {
            "id": ctx.request_id,
            "method": ctx.method,
            "path": ctx.path,
            "status": status,
            "ms": round(elapsed_ms, 2),
            "thread": ctx.thread,
        }
        with self.state.lock:
            self.state.counts[f"{ctx.method} {ctx.path}"] += 1
            self.state.recent.append(item)
            if len(self.state.recent) > self.cfg.max_recent:
                self.state.recent = self.state.recent[-self.cfg.max_recent :]

    def health(self) -> Response:
        snap = self.snapshot()
        return Response.json({"ok": True, "uptime_s": snap["uptime_s"], "counts": snap["counts"]})

    def snapshot(self) -> dict[str, Any]:
        now = time.time()
        with self.state.lock:
            counts = dict(self.state.counts)
            jobs = list(self.state.jobs.values())
            recent = list(self.state.recent)
        return {
            "uptime_s": round(now - self.state.started_at, 3),
            "counts": counts,
            "jobs": [asdict(j) for j in jobs],
            "recent": recent,
        }

    def quote(self, *, order: Order) -> Quote:
        base = order.subtotal
        discount = max(0.0, min(order.discount, base))
        taxed = (base - discount) * max(0.0, order.tax_rate)
        total = base - discount + taxed
        breakdown = {
            "subtotal": round(base, 2),
            "discount": round(discount, 2),
            "tax": round(taxed, 2),
        }
        return Quote(order_id=order.id, total=round(total, 2), breakdown=breakdown)

    def enqueue_job(self, *, kind: str, params: dict[str, Any]) -> Job:
        with self.state.lock:
            self.state.job_seq += 1
            job_id = self.state.job_seq
            job = Job(id=job_id, kind=kind, params=params)
            self.state.jobs[job_id] = job
        self.state.job_queue.put(job_id)
        return job

    def get_job(self, job_id: int) -> Job | None:
        with self.state.lock:
            return self.state.jobs.get(job_id)

    def handle(self, *, method: str, raw_path: str) -> Response:
        parsed = urlparse(raw_path)
        path = parsed.path or "/"
        query = {k: list(v) for k, v in parse_qs(parsed.query, keep_blank_values=True).items()}
        ctx = self.new_context(method=method, path=path, query=query)
        response: Response | None = None
        try:
            match (method, path):
                case ("GET", "/") | ("GET", "/help"):
                    response = self._help()
                case ("GET", "/health"):
                    response = self.health()
                case ("GET", "/stats"):
                    response = Response.json(self.snapshot())
                case ("GET", "/orders/quote"):
                    response = self._orders_quote(query)
                case ("GET", "/compute/primes"):
                    response = self._compute_primes(query)
                case ("GET", "/compute/mandelbrot"):
                    response = self._compute_mandelbrot(query)
                case ("GET", "/jobs/enqueue"):
                    response = self._jobs_enqueue(query)
                case _ if path.startswith("/jobs/"):
                    response = self._jobs_get(path)
                case ("GET", "/debug/sleep"):
                    response = self._debug_sleep(query)
                case ("GET", "/debug/error"):
                    response = self._debug_error(query)
                case _:
                    response = Response.json(
                        {"error": "not_found", "path": path, "hint": "try /help"},
                        status=HTTPStatus.NOT_FOUND,
                    )
        except Exception as exc:
            response = Response.json(
                {
                    "error": "internal_error",
                    "type": type(exc).__name__,
                    "message": str(exc),
                },
                status=HTTPStatus.INTERNAL_SERVER_ERROR,
            )
        finally:
            if response is not None:
                self.record(ctx, response.status)

        assert response is not None
        return response

    def _help(self) -> Response:
        return Response.text(
            "\n".join(
                [
                    "yathaavat vanilla service",
                    "",
                    "Endpoints:",
                    "  GET /health",
                    "  GET /stats",
                    "  GET /orders/quote?id=8812&subtotal=129.95&tax_rate=0.08&discount=0",
                    "  GET /compute/primes?limit=200000",
                    "  GET /compute/mandelbrot?width=90&height=24&iter=60",
                    "  GET /jobs/enqueue?kind=primes&limit=250000",
                    "  GET /jobs/<id>",
                    "  GET /debug/sleep?ms=500",
                    "  GET /debug/error?mode=key",
                    "",
                    "Tip: attach yathaavat via Ctrl+A (safe attach on macOS requires sudo).",
                ]
            )
        )

    def _orders_quote(self, query: dict[str, list[str]]) -> Response:
        order_id = _as_int((query.get("id") or ["8812"])[0], 8812)
        subtotal = _as_float((query.get("subtotal") or ["129.95"])[0], 129.95)
        tax_rate = _as_float((query.get("tax_rate") or ["0.08"])[0], 0.08)
        discount = _as_float((query.get("discount") or ["0.0"])[0], 0.0)
        order = Order(id=order_id, subtotal=subtotal, tax_rate=tax_rate, discount=discount)
        quote = self.quote(order=order)
        return Response.json(asdict(quote))

    def _compute_primes(self, query: dict[str, list[str]]) -> Response:
        limit = _as_int((query.get("limit") or ["200000"])[0], 200000)
        stats = prime_stats(limit)
        return Response.json(asdict(stats))

    def _compute_mandelbrot(self, query: dict[str, list[str]]) -> Response:
        width = _as_int((query.get("width") or ["90"])[0], 90)
        height = _as_int((query.get("height") or ["24"])[0], 24)
        max_iter = _as_int((query.get("iter") or ["60"])[0], 60)
        art = mandelbrot_ascii(width=width, height=height, max_iter=max_iter)
        return Response.text(art)

    def _jobs_enqueue(self, query: dict[str, list[str]]) -> Response:
        kind = (query.get("kind") or ["primes"])[0].strip().lower() or "primes"
        match kind:
            case "primes":
                limit = _as_int((query.get("limit") or ["250000"])[0], 250000)
                job = self.enqueue_job(kind=kind, params={"limit": limit})
            case "mandelbrot":
                w = _as_int((query.get("width") or ["120"])[0], 120)
                h = _as_int((query.get("height") or ["30"])[0], 30)
                it = _as_int((query.get("iter") or ["80"])[0], 80)
                job = self.enqueue_job(kind=kind, params={"width": w, "height": h, "iter": it})
            case _:
                return Response.json(
                    {"error": "unknown_job_kind", "kind": kind},
                    status=HTTPStatus.BAD_REQUEST,
                )
        return Response.json({"job_id": job.id, "kind": job.kind, "params": job.params})

    def _jobs_get(self, path: str) -> Response:
        try:
            job_id = int(path.rsplit("/", 1)[-1])
        except ValueError:
            return Response.json(
                {"error": "bad_job_id", "path": path}, status=HTTPStatus.BAD_REQUEST
            )
        job = self.get_job(job_id)
        if job is None:
            return Response.json({"error": "job_not_found", "job_id": job_id}, status=404)
        payload = asdict(job)
        if isinstance(job.result, str) and len(job.result) > 240:
            payload["result_preview"] = job.result[:240] + "…"
            payload["result"] = None
        return Response.json(payload)

    def _debug_sleep(self, query: dict[str, list[str]]) -> Response:
        ms = _as_int((query.get("ms") or ["500"])[0], 500)
        ms = max(0, min(ms, 30_000))
        time.sleep(ms / 1000.0)
        return Response.json({"slept_ms": ms})

    def _debug_error(self, query: dict[str, list[str]]) -> Response:
        mode = (query.get("mode") or ["value"])[0]
        match mode:
            case "key":
                data = {"ok": 1}
                _ = data["missing"]
            case "value":
                raise ValueError("boom: debug/error value")
            case "group":
                raise ExceptionGroup(
                    "boom: debug/error group",
                    [
                        ValueError("bad_value"),
                        KeyError("missing_key"),
                    ],
                )
            case _:
                raise RuntimeError(f"unknown mode: {mode}")
        return Response.json({"unreachable": True})


def _job_worker(service: VanillaService, worker_id: int) -> None:
    rnd = random.Random(worker_id)
    while not service.state.stop.is_set():
        try:
            job_id = service.state.job_queue.get(timeout=0.25)
        except queue.Empty:
            continue
        job = service.get_job(job_id)
        if job is None:
            continue
        job.started_at = time.time()
        job.status = "running"
        try:
            match job.kind:
                case "primes":
                    limit = int(job.params.get("limit") or 250_000)
                    # Add a little nondeterminism to make traces interesting.
                    if rnd.random() < 0.02:
                        limit = max(10, limit - 1)
                    job.result = asdict(prime_stats(limit))
                case "mandelbrot":
                    w = int(job.params.get("width") or 120)
                    h = int(job.params.get("height") or 30)
                    it = int(job.params.get("iter") or 80)
                    job.result = mandelbrot_ascii(width=w, height=h, max_iter=it)
                case _:
                    raise ValueError(f"unknown job kind: {job.kind}")
            job.status = "done"
        except Exception as exc:
            job.status = "error"
            job.error = f"{type(exc).__name__}: {exc}"
        finally:
            job.finished_at = time.time()


def _serve(cfg: ServiceConfig) -> None:
    service = VanillaService(cfg=cfg)

    for idx in range(cfg.workers):
        t = threading.Thread(
            target=_job_worker,
            name=f"worker-{idx}",
            args=(service, idx),
            daemon=True,
        )
        t.start()

    def make_handler() -> type[BaseHTTPRequestHandler]:
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                response = service.handle(method="GET", raw_path=self.path)
                try:
                    self.send_response(response.status)
                    for k, v in response.headers.items():
                        self.send_header(k, v)
                    self.end_headers()
                    self.wfile.write(response.body)
                except (BrokenPipeError, ConnectionResetError):
                    # Common during debugging: the server thread pauses while the client times out.
                    return

            def log_message(self, fmt: str, *args: object) -> None:
                # Keep the service quiet; yathaavat transcript is the primary log surface.
                return

        return Handler

    httpd = ThreadingHTTPServer((cfg.host, cfg.port), make_handler())
    base = f"http://{cfg.host}:{cfg.port}"
    print(f"VANILLA_SERVICE_PID {os.getpid()}", flush=True)
    print(f"VANILLA_SERVICE_LISTENING {base}", flush=True)
    print(f"Try: curl -fsS {base}/help", flush=True)
    try:
        httpd.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        service.state.stop.set()
        httpd.server_close()


def _parse_args(argv: list[str] | None = None) -> ServiceConfig:
    parser = argparse.ArgumentParser(prog="vanilla_service")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--max-recent", type=int, default=200)
    ns = parser.parse_args(argv)
    return ServiceConfig(
        host=str(ns.host),
        port=int(ns.port),
        workers=max(1, int(ns.workers)),
        max_recent=max(25, int(ns.max_recent)),
    )


def main(argv: list[str] | None = None) -> None:
    cfg = _parse_args(argv)
    _serve(cfg)


if __name__ == "__main__":
    main()
