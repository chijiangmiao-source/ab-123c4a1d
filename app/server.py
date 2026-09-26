"""束线联锁规程 ioco 静止输出复核服务。

仅使用 Python 标准库：
  GET  /                 复核页面
  GET  /static/app.js    前端脚本
  POST /api/verify       提交旧规程与候选规程，读取复核结论

POST /api/verify 请求体：
  {"spec":    {"name": "旧规程", "locations": ..., "initial": ...,
               "transitions": [{"from", "action", "to"}, ...]},
   "candidate": {...同上...}}

响应（HTTP 200，无论一致与否）：
  {"verdict": "consistent" | "inconsistent", ...证据...}
校验失败时 HTTP 400：
  {"errors": [{"side": "spec|candidate", "message": "..."}]}
非法输入会清除先前结论——结论完全由本次请求计算，服务端不保存状态。
"""

from __future__ import annotations

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

try:  # 同时支持 python -m app.server 与在 app 目录内直接运行
    from app.spec import (
        KIND_CN,
        QUIESCENCE_LABEL,
        SpecError,
        check_ioco,
        parse_spec,
    )
except ImportError:  # pragma: no cover - 直接运行入口
    from spec import (  # type: ignore
        KIND_CN,
        QUIESCENCE_LABEL,
        SpecError,
        check_ioco,
        parse_spec,
    )

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
MAX_BODY = 256 * 1024


def _build_result(spec_payload: dict, cand_payload: dict) -> dict:
    """解析、校验两份规程并执行 ioco 判定；收集双侧全部错误。"""
    errors = []
    spec = cand = None
    for side, label, payload in (
        ("spec", "旧规程", spec_payload),
        ("candidate", "候选规程", cand_payload),
    ):
        try:
            parsed = parse_spec(label, payload if isinstance(payload, dict) else {})
        except SpecError as exc:
            errors.append({"side": side, "message": str(exc)})
            continue
        if side == "spec":
            spec = parsed
        else:
            cand = parsed

    if errors:
        return {"ok": False, "errors": errors}

    verdict = check_ioco(spec, cand)  # type: ignore[arg-type]
    return {
        "ok": True,
        "verdict": "consistent" if verdict.conforms else "inconsistent",
        "trace": verdict.trace,
        "steps": [
            {
                "label": s.label,
                "kind": s.kind,
                "kind_cn": ("初始" if s.kind == "initial" else KIND_CN[s.kind]),
                "spec_states": s.spec_states,
                "candidate_states": s.cand_states,
            }
            for s in verdict.steps
        ],
        "candidate_outputs": verdict.candidate_outputs,
        "spec_allowed_outputs": verdict.spec_allowed_outputs,
        "offending_outputs": verdict.offending,
        "spec_quiescent_states": verdict.spec_quiescent_states,
        "candidate_quiescent_states": verdict.cand_quiescent_states,
        "quiescence_label": QUIESCENCE_LABEL,
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "IocoVerify/1.0"

    def _send_json(self, status: int, obj: dict) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, rel: str, content_type: str) -> None:
        path = os.path.normpath(os.path.join(STATIC_DIR, rel))
        if not path.startswith(STATIC_DIR + os.sep) or not os.path.isfile(path):
            self.send_error(404)
            return
        with open(path, "rb") as fh:
            body = fh.read()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - http.server 接口
        route = urlparse(self.path).path
        if route in ("/", "/index.html"):
            self._send_file("index.html", "text/html; charset=utf-8")
        elif route == "/static/app.js":
            self._send_file("app.js", "application/javascript; charset=utf-8")
        elif route == "/healthz":
            self._send_json(200, {"status": "ok"})
        else:
            self.send_error(404)

    def do_POST(self) -> None:  # noqa: N802
        if urlparse(self.path).path != "/api/verify":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = -1
        if length <= 0 or length > MAX_BODY:
            self._send_json(400, {"errors": [
                {"side": "spec", "message": "请求体缺失或超出大小限制"}
            ]})
            return
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send_json(400, {"errors": [
                {"side": "spec", "message": "请求体不是合法的 UTF-8 JSON"}
            ]})
            return
        if not isinstance(payload, dict):
            self._send_json(400, {"errors": [
                {"side": "spec", "message": "请求顶层必须是 JSON 对象"}
            ]})
            return
        result = _build_result(payload.get("spec"), payload.get("candidate"))
        self._send_json(200 if result["ok"] else 400, result)

    def log_message(self, fmt: str, *args) -> None:  # 静默常规访问日志
        if os.environ.get("IOCO_HTTP_LOG"):
            super().log_message(fmt, *args)


def create_server(host: str, port: int) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    return server


def main() -> None:
    host = os.environ.get("IOCO_HOST", "0.0.0.0")
    port = int(os.environ.get("IOCO_PORT", "8080"))
    server = create_server(host, port)
    print(f"ioco 静止输出复核服务监听 http://{host}:{port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
