#!/usr/bin/env python3
"""Compose verify 服务入口：

依次执行
  1. 代码测试（unittest 全量）
  2. 构建检查（compileall 字节码编译）
  3. HTTP 冒烟（经真实接口核对「静默后报警」反例，并附带改名一致用例）

全部通过则以退出码 0 结束；任一步失败立即报告并以非 0 退出。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB_URL = os.environ.get("IOCO_WEB_URL", "http://web:8080")
Q = "静止"


def report(step: str, ok: bool, detail: str = "") -> bool:
    mark = "PASS" if ok else "FAIL"
    print(f"[verify] {mark} - {step}" + (f"\n         {detail}" if detail else ""),
          flush=True)
    return ok


def run_code_tests() -> bool:
    proc = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
        cwd=ROOT,
    )
    return report("代码测试（unittest 全量）", proc.returncode == 0,
                  "" if proc.returncode == 0 else f"unittest 退出码 {proc.returncode}")


def run_build_check() -> bool:
    proc = subprocess.run(
        [sys.executable, "-m", "compileall", "-q", "app", "tests", "verify"],
        cwd=ROOT,
    )
    return report("构建检查（compileall 字节码编译）", proc.returncode == 0,
                  "" if proc.returncode == 0 else f"compileall 退出码 {proc.returncode}")


def wait_for_web(timeout: float = 30.0) -> bool:
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(WEB_URL + "/healthz", timeout=2) as resp:
                if resp.status == 200:
                    return True
        except (urllib.error.URLError, OSError) as exc:
            last = str(exc)
        time.sleep(0.5)
    return report(f"等待 {WEB_URL}/healthz 就绪", False, last or "超时")


def post_verify(body: dict) -> dict:
    req = urllib.request.Request(
        WEB_URL + "/api/verify",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read().decode("utf-8"))


def quiet_spec():
    return {
        "name": "旧规程",
        "locations": "S0,S1",
        "initial": "S0",
        "transitions": [
            {"from": "S0", "action": "命令?", "to": "S1"},
            {"from": "S1", "action": Q, "to": "S1"},
        ],
    }


def run_http_smoke() -> bool:
    # 1) 静默后报警反例：候选命令? -> 静默τ -> 报警!，旧规程命令后只能静止
    counter = {
        "spec": quiet_spec(),
        "candidate": {
            "name": "候选规程",
            "locations": "C0,C1,C2",
            "initial": "C0",
            "transitions": [
                {"from": "C0", "action": "命令?", "to": "C1"},
                {"from": "C1", "action": "静默", "to": "C2"},
                {"from": "C2", "action": "报警!", "to": "C2"},
            ],
        },
    }
    try:
        data = post_verify(counter)
    except (urllib.error.URLError, OSError) as exc:
        return report("HTTP 冒烟：静默后报警反例", False, f"接口请求失败：{exc}")

    checks = [
        ("verdict == inconsistent", data.get("verdict") == "inconsistent"),
        ("最短历史 == ['命令?']", data.get("trace") == ["命令?"]),
        ("未允许输出 == ['报警!']", data.get("offending_outputs") == ["报警!"]),
        ("旧规程允许输出 == ['静止']",
         data.get("spec_allowed_outputs") == [Q]),
        ("候选输出含报警!", "报警!" in (data.get("candidate_outputs") or [])),
        ("末步候选闭包 == ['C1','C2']（纳入静默 τ）",
         data.get("steps", [{}])[-1].get("candidate_states") == ["C1", "C2"]),
        ("末步旧规程闭包 == ['S1']",
         data.get("steps", [{}])[-1].get("spec_states") == ["S1"]),
    ]
    failed = [name for name, ok in checks if not ok]
    if failed:
        return report("HTTP 冒烟：静默后报警反例", False,
                      "未满足：" + "；".join(failed) + f"；响应={json.dumps(data, ensure_ascii=False)}")

    # 2) 控制用例：仅位置改名 => 必须一致
    renamed = {
        "spec": quiet_spec(),
        "candidate": {
            "name": "候选规程",
            "locations": "待命,执行",
            "initial": "待命",
            "transitions": [
                {"from": "待命", "action": "命令?", "to": "执行"},
                {"from": "执行", "action": Q, "to": "执行"},
            ],
        },
    }
    try:
        ok_data = post_verify(renamed)
    except (urllib.error.URLError, OSError) as exc:
        return report("HTTP 冒烟：改名一致控制用例", False, f"接口请求失败：{exc}")
    if ok_data.get("verdict") != "consistent":
        return report("HTTP 冒烟：改名一致控制用例", False,
                      f"期望 consistent，得到 {json.dumps(ok_data, ensure_ascii=False)}")

    report("HTTP 冒烟：静默后报警反例（含逐步闭包与输出集合核对）", True)
    report("HTTP 冒烟：仅位置改名一致控制用例", True)
    return True


def main() -> int:
    print(f"[verify] 目标服务：{WEB_URL}", flush=True)
    if not run_code_tests():
        code = 1
    elif not run_build_check():
        code = 2
    elif not wait_for_web():
        code = 3
    elif not run_http_smoke():
        code = 4
    else:
        code = 0
    print(f"[verify] 全部核对完成，退出码 {code}", flush=True)
    return code


if __name__ == "__main__":
    sys.exit(main())
