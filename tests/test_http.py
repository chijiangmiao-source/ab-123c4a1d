"""真实 HTTP 接口冒烟测试：启动服务线程，经网络端口提交与读取结论。"""

import json
import threading
import unittest
import urllib.request
import urllib.error

from app.server import create_server

Q = "静止"


def payload(locs, init, trans):
    return {"locations": ",".join(locs), "initial": init,
            "transitions": [{"from": a, "action": b, "to": c} for a, b, c in trans]}


class HttpApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = create_server("127.0.0.1", 0)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def request(self, path, body=None):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(self.base + path, data=data,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    def test_healthz_and_page(self):
        status, body = self.request("/healthz")
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "ok")
        with urllib.request.urlopen(self.base + "/", timeout=5) as resp:
            html = resp.read().decode("utf-8")
        self.assertIn("ioco", html)

    def test_consistent_via_http(self):
        body = {
            "spec": payload(["S0", "S1"], "S0",
                            [("S0", "命令?", "S1"), ("S1", Q, "S1")]),
            "candidate": payload(["待命", "执行"], "待命",
                                 [("待命", "命令?", "执行"), ("执行", Q, "执行")]),
        }
        status, data = self.request("/api/verify", body)
        self.assertEqual(status, 200)
        self.assertEqual(data["verdict"], "consistent")

    def test_alarm_counterexample_via_http(self):
        """静默后报警反例（verify 服务冒烟核对的同款场景）。"""
        body = {
            "spec": payload(["S0", "S1"], "S0",
                            [("S0", "命令?", "S1"), ("S1", Q, "S1")]),
            "candidate": payload(["C0", "C1", "C2"], "C0",
                                 [("C0", "命令?", "C1"),
                                  ("C1", "静默", "C2"),
                                  ("C2", "报警!", "C2")]),
        }
        status, data = self.request("/api/verify", body)
        self.assertEqual(status, 200)
        self.assertEqual(data["verdict"], "inconsistent")
        self.assertEqual(data["trace"], ["命令?"])
        self.assertEqual(data["offending_outputs"], ["报警!"])
        self.assertEqual(data["spec_allowed_outputs"], [Q])
        self.assertEqual(data["steps"][-1]["candidate_states"], ["C1", "C2"])

    def test_validation_error_clears_conclusion(self):
        # 先得到一个合法结论
        good = {
            "spec": payload(["S"], "S", [("S", Q, "S")]),
            "candidate": payload(["C"], "C", [("C", Q, "C")]),
        }
        status, data = self.request("/api/verify", good)
        self.assertEqual(status, 200)
        # 再提交含悬空迁移的规程：必须 400 且只返回定位错误、无结论字段
        bad = {
            "spec": payload(["S"], "S", [("S", "报警!", "幽灵")]),
            "candidate": payload(["C"], "C", [("C", Q, "C")]),
        }
        status, data = self.request("/api/verify", bad)
        self.assertEqual(status, 400)
        self.assertFalse(data["ok"])
        self.assertIn("悬空迁移", data["errors"][0]["message"])
        self.assertEqual(data["errors"][0]["side"], "spec")
        self.assertNotIn("verdict", data)

    def test_bad_json(self):
        req = urllib.request.Request(
            self.base + "/api/verify", data=b"{not json",
            headers={"Content-Type": "application/json"})
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req, timeout=5)
        self.assertEqual(ctx.exception.code, 400)


if __name__ == "__main__":
    unittest.main()
