# /// script
# requires-python = ">=3.14"
# dependencies = [
#   "debugpy",
# ]
# ///

from __future__ import annotations

import json
import os
import threading
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import debugpy
from demo_service_compute import mandelbrot_ascii, prime_stats


@dataclass(frozen=True, slots=True)
class ServiceConfig:
    http_host: str = "127.0.0.1"
    http_port: int = 8000
    dap_host: str = "127.0.0.1"
    dap_port: int = 5678
    enable_debugpy: bool = True


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
    tax: float
    discount: float = 0.0


@dataclass(frozen=True, slots=True)
class PricingResult:
    order_id: int
    total: float
    breakdown: dict[str, float]


@dataclass(slots=True)
class Job:
    id: int
    kind: str
    created_at: float
    status: str = "queued"
    started_at: float | None = None
    finished_at: float | None = None
    result: object | None = None
    error: str | None = None


@dataclass(slots=True)
class ServiceState:
    started_at: float = field(default_factory=time.time)
    request_seq: int = 0
    job_seq: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock)
    counts: Counter[str] = field(default_factory=Counter)
    jobs: dict[int, Job] = field(default_factory=dict)
    hot_cache: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Response:
    status: int
    headers: dict[str, str]
    body: bytes

    @staticmethod
    def json(payload: object, *, status: int = 200) -> Response:
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


class DemoService:
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

    def handle(self, ctx: RequestContext) -> Response:
        self._log(ctx, f"{ctx.method} {ctx.path}")
        with self.state.lock:
            self.state.counts[ctx.path] += 1

        try:
            match (ctx.method, ctx.path):
                case ("GET", "/"):
                    return self._index(ctx)
                case ("GET", "/health"):
                    return self._health(ctx)
                case ("GET", "/orders/checkout"):
                    return self._orders_checkout(ctx)
                case ("GET", "/cpu/primes"):
                    return self._cpu_primes(ctx)
                case ("GET", "/cpu/mandelbrot"):
                    return self._cpu_mandelbrot(ctx)
                case ("POST", "/jobs/submit"):
                    return self._jobs_submit(ctx)
                case ("GET", "/jobs"):
                    return self._jobs_list(ctx)
                case ("GET", path) if path.startswith("/jobs/"):
                    return self._jobs_get(ctx, path)
                case ("GET", "/debug/break"):
                    return self._debug_break(ctx)
                case ("GET", "/debug/boom"):
                    return self._debug_boom(ctx)
                case _:
                    return Response.json(
                        {"error": "not_found", "path": ctx.path, "method": ctx.method},
                        status=HTTPStatus.NOT_FOUND,
                    )
        except Exception as exc:
            self._log(ctx, f"error: {exc!r}")
            return Response.json(
                {"error": "internal_error", "detail": repr(exc)},
                status=HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    def _index(self, ctx: RequestContext) -> Response:
        base = f"http://{self.cfg.http_host}:{self.cfg.http_port}"
        endpoints = {
            "health": f"{base}/health",
            "orders_checkout": f"{base}/orders/checkout?id=8812&subtotal=129.95&tax=10.40",
            "cpu_primes": f"{base}/cpu/primes?limit=200000",
            "cpu_mandelbrot": f"{base}/cpu/mandelbrot?width=120&height=40&iters=80",
            "jobs_submit": f"curl -X POST {base}/jobs/submit -d 'kind=primes&limit=250000'",
            "jobs_list": f"{base}/jobs",
            "debug_break": f"{base}/debug/break",
            "debug_boom": f"{base}/debug/boom",
        }
        return Response.json(
            {
                "service": "yathaavat-demo-service",
                "debugpy": {
                    "enabled": self.cfg.enable_debugpy,
                    "dap": f"{self.cfg.dap_host}:{self.cfg.dap_port}",
                    "client_connected": bool(debugpy.is_client_connected()),
                },
                "endpoints": endpoints,
                "tip": "Use /debug/break after connecting with yathaavat (Ctrl+K).",
            }
        )

    def _health(self, ctx: RequestContext) -> Response:
        with self.state.lock:
            counts = dict(self.state.counts)
            active_jobs = sum(
                1 for j in self.state.jobs.values() if j.status in {"queued", "running"}
            )
        return Response.json(
            {
                "ok": True,
                "pid": os.getpid(),
                "uptime_s": round(time.time() - self.state.started_at, 3),
                "requests": counts,
                "jobs_active": active_jobs,
            }
        )

    def _orders_checkout(self, ctx: RequestContext) -> Response:
        order = _parse_order(ctx.query)
        result = _checkout(order)
        self.state.hot_cache[f"order:{order.id}"] = {
            "order": asdict(order),
            "result": asdict(result),
        }
        return Response.json({"order": asdict(order), "result": asdict(result)})

    def _cpu_primes(self, ctx: RequestContext) -> Response:
        limit = _q_int(ctx.query, "limit", default=200_000, min_=1, max_=2_000_000)
        t0 = time.perf_counter()
        stats = prime_stats(limit)
        dt_ms = (time.perf_counter() - t0) * 1000.0
        self.state.hot_cache[f"primes:{limit}"] = stats
        return Response.json(
            {
                "kind": "primes",
                "duration_ms": round(dt_ms, 3),
                "stats": asdict(stats),
                "cache_info": prime_stats.cache_info()._asdict(),
            }
        )

    def _cpu_mandelbrot(self, ctx: RequestContext) -> Response:
        width = _q_int(ctx.query, "width", default=120, min_=20, max_=240)
        height = _q_int(ctx.query, "height", default=40, min_=10, max_=80)
        iters = _q_int(ctx.query, "iters", default=80, min_=10, max_=250)
        t0 = time.perf_counter()
        art = mandelbrot_ascii(width=width, height=height, max_iter=iters)
        dt_ms = (time.perf_counter() - t0) * 1000.0
        self.state.hot_cache["mandelbrot:last"] = {"width": width, "height": height, "iters": iters}
        payload = f"{art}\n\n# {width=} {height=} {iters=}  ({dt_ms:.1f}ms)"
        return Response.text(payload, content_type="text/plain")

    def _jobs_submit(self, ctx: RequestContext) -> Response:
        body = ctx.query
        kind = (body.get("kind") or [""])[0].strip() or "primes"

        with self.state.lock:
            self.state.job_seq += 1
            job_id = self.state.job_seq
            job = Job(id=job_id, kind=kind, created_at=time.time())
            self.state.jobs[job_id] = job

        def run_job() -> None:
            job.started_at = time.time()
            job.status = "running"
            try:
                match kind:
                    case "primes":
                        limit = _q_int(body, "limit", default=250_000, min_=1, max_=2_000_000)
                        job.result = asdict(prime_stats(limit))
                    case "mandelbrot":
                        width = _q_int(body, "width", default=120, min_=20, max_=240)
                        height = _q_int(body, "height", default=40, min_=10, max_=80)
                        iters = _q_int(body, "iters", default=80, min_=10, max_=250)
                        job.result = mandelbrot_ascii(width=width, height=height, max_iter=iters)
                    case _:
                        raise ValueError(f"Unknown kind: {kind}")
                job.status = "done"
            except Exception as exc:
                job.status = "error"
                job.error = repr(exc)
            finally:
                job.finished_at = time.time()

        threading.Thread(target=run_job, name=f"job-{job_id}", daemon=True).start()
        return Response.json(
            {"job_id": job_id, "kind": kind, "status": job.status}, status=HTTPStatus.ACCEPTED
        )

    def _jobs_list(self, ctx: RequestContext) -> Response:
        with self.state.lock:
            jobs = list(self.state.jobs.values())
        jobs.sort(key=lambda j: j.id, reverse=True)
        return Response.json({"jobs": [_job_summary(j) for j in jobs[:50]]})

    def _jobs_get(self, ctx: RequestContext, path: str) -> Response:
        try:
            job_id = int(path.rsplit("/", 1)[-1])
        except ValueError:
            return Response.json({"error": "invalid_job_id"}, status=HTTPStatus.BAD_REQUEST)

        with self.state.lock:
            job = self.state.jobs.get(job_id)

        if job is None:
            return Response.json(
                {"error": "job_not_found", "job_id": job_id}, status=HTTPStatus.NOT_FOUND
            )

        return Response.json(
            {
                "job": {
                    **_job_summary(job),
                    "result_preview": _preview(job.result, max_len=700),
                    "error": job.error,
                }
            }
        )

    def _debug_break(self, ctx: RequestContext) -> Response:
        # Locals here are intentionally rich to exercise yathaavat's variable tree.
        with self.state.lock:
            recent_jobs = list(self.state.jobs.values())[-5:]
            counts = dict(self.state.counts)
        bundle = {
            "ctx": asdict(ctx),
            "cwd": str(Path.cwd()),
            "counts": counts,
            "recent_jobs": [_job_summary(j) for j in recent_jobs],
            "hot_cache_keys": sorted(self.state.hot_cache.keys())[-10:],
        }

        if debugpy.is_client_connected():
            debugpy.breakpoint()

        return Response.json({"ok": True, "note": "resumed", "bundle_keys": sorted(bundle.keys())})

    def _debug_boom(self, ctx: RequestContext) -> Response:
        # A controlled exception route to test transcript + error handling.
        raise RuntimeError(f"boom from request {ctx.request_id}")

    def _log(self, ctx: RequestContext, msg: str) -> None:
        now = time.strftime("%H:%M:%S")
        print(f"{now}  req={ctx.request_id}  {ctx.thread}  {msg}", flush=True)


class DemoHttpServer(ThreadingHTTPServer):
    def __init__(
        self,
        server_address: tuple[str, int],
        request_handler_class: type[BaseHTTPRequestHandler],
        *,
        service: DemoService,
    ) -> None:
        super().__init__(server_address, request_handler_class)
        self.service = service


class DemoHandler(BaseHTTPRequestHandler):
    server: DemoHttpServer  # type: ignore[assignment]

    def do_GET(self) -> None:
        self._dispatch("GET")

    def do_POST(self) -> None:
        self._dispatch("POST")

    def log_message(self, _format: str, *args: object) -> None:
        # Silence default http.server logging; we do our own structured logs.
        _ = args

    def _dispatch(self, method: str) -> None:
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query, keep_blank_values=True)
        if method == "POST":
            content_len = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(content_len) if content_len > 0 else b""
            try:
                form = parse_qs(raw.decode("utf-8"), keep_blank_values=True)
            except UnicodeDecodeError:
                form = {}
            query = {**query, **form}

        ctx = self.server.service.new_context(method=method, path=parsed.path, query=query)
        resp = self.server.service.handle(ctx)

        self.send_response(int(resp.status))
        for k, v in resp.headers.items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(resp.body)))
        self.end_headers()
        self.wfile.write(resp.body)


def _q_int(
    query: dict[str, list[str]],
    key: str,
    *,
    default: int,
    min_: int | None = None,
    max_: int | None = None,
) -> int:
    raw = (query.get(key) or [str(default)])[0]
    try:
        value = int(raw)
    except ValueError:
        value = default
    if min_ is not None:
        value = max(value, min_)
    if max_ is not None:
        value = min(value, max_)
    return value


def _parse_order(query: dict[str, list[str]]) -> Order:
    oid = _q_int(query, "id", default=8812, min_=1)
    subtotal = float((query.get("subtotal") or ["129.95"])[0])
    tax = float((query.get("tax") or ["10.40"])[0])
    discount = float((query.get("discount") or ["0.0"])[0])
    return Order(id=oid, subtotal=subtotal, tax=tax, discount=discount)


def _checkout(order: Order) -> PricingResult:
    _validate(order)
    total = order.subtotal + order.tax - order.discount
    breakdown = {"subtotal": order.subtotal, "tax": order.tax, "discount": order.discount}
    return PricingResult(order_id=order.id, total=round(total, 2), breakdown=breakdown)


def _validate(order: Order) -> None:
    if order.subtotal < 0 or order.tax < 0 or order.discount < 0:
        raise ValueError("Negative amount is invalid")
    if order.discount > order.subtotal:
        raise ValueError("Discount exceeds subtotal")


def _job_summary(job: Job) -> dict[str, object]:
    duration_ms: float | None = None
    if job.started_at is not None and job.finished_at is not None:
        duration_ms = (job.finished_at - job.started_at) * 1000.0
    return {
        "id": job.id,
        "kind": job.kind,
        "status": job.status,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
        "duration_ms": round(duration_ms, 3) if duration_ms is not None else None,
    }


def _preview(value: object, *, max_len: int) -> str:
    if value is None:
        return ""
    s = value if isinstance(value, str) else json.dumps(value, indent=2, sort_keys=True)
    if len(s) <= max_len:
        return s
    return s[: max_len - 1] + "…"


def _load_config() -> ServiceConfig:
    def env_int(name: str, default: int) -> int:
        raw = os.environ.get(name, "").strip()
        if not raw:
            return default
        try:
            return int(raw)
        except ValueError:
            return default

    def env_bool(name: str, default: bool) -> bool:
        raw = os.environ.get(name, "").strip().lower()
        if not raw:
            return default
        return raw in {"1", "true", "yes", "on"}

    return ServiceConfig(
        http_host=os.environ.get("YATHAAVAT_HTTP_HOST", "127.0.0.1").strip() or "127.0.0.1",
        http_port=env_int("YATHAAVAT_HTTP_PORT", 8000),
        dap_host=os.environ.get("YATHAAVAT_DAP_HOST", "127.0.0.1").strip() or "127.0.0.1",
        dap_port=env_int("YATHAAVAT_DAP_PORT", 5678),
        enable_debugpy=env_bool("YATHAAVAT_ENABLE_DEBUGPY", True),
    )


def _start_debugpy(cfg: ServiceConfig) -> None:
    if not cfg.enable_debugpy:
        print("DEBUGPY disabled (YATHAAVAT_ENABLE_DEBUGPY=0)", flush=True)
        return
    debugpy.listen((cfg.dap_host, cfg.dap_port))
    print(f"DEBUGPY_LISTENING {cfg.dap_host}:{cfg.dap_port}", flush=True)


def _start_server(cfg: ServiceConfig) -> None:
    service = DemoService(cfg=cfg)
    http_addr = (cfg.http_host, cfg.http_port)
    server = DemoHttpServer(http_addr, DemoHandler, service=service)
    print(f"SERVICE_LISTENING http://{cfg.http_host}:{cfg.http_port}", flush=True)
    print("Try: curl http://127.0.0.1:8000/health", flush=True)
    server.serve_forever(poll_interval=0.2)


def main() -> None:
    cfg = _load_config()
    _start_debugpy(cfg)
    try:
        _start_server(cfg)
    except KeyboardInterrupt:
        print("Shutting down.", flush=True)


if __name__ == "__main__":
    main()
