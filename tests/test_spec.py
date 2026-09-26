"""ioco 判定与规程校验的单元测试。"""

import unittest

from app.spec import (
    QUIESCENCE_LABEL,
    SpecError,
    _tau_closure,
    check_ioco,
    parse_spec,
)

Q = QUIESCENCE_LABEL


def spec_payload(locs, init, trans):
    return {"locations": ",".join(locs), "initial": init,
            "transitions": [{"from": a, "action": b, "to": c} for a, b, c in trans]}


def ioco(s, c):
    return check_ioco(parse_spec("旧", s), parse_spec("候选", c))


# 需求中的三个基准场景 -------------------------------------------------------

SPEC_QUIET = spec_payload(
    ["S0", "S1"], "S0",
    [("S0", "命令?", "S1"), ("S1", Q, "S1")])
CAND_RENAMED = spec_payload(
    ["待命", "执行"], "待命",
    [("待命", "命令?", "执行"), ("执行", Q, "执行")])
CAND_ALARM = spec_payload(
    ["C0", "C1"], "C0",
    [("C0", "命令?", "C1"), ("C1", "报警!", "C1")])
CAND_TAU_CONFIRM = spec_payload(
    ["C0", "C1", "C2"], "C0",
    [("C0", "命令?", "C1"), ("C1", "静默", "C2"), ("C2", "确认!", "C2")])


class ScenarioTests(unittest.TestCase):

    def test_renamed_locations_are_consistent(self):
        """仅位置名称不同、输入输出与静止行为相同 => 一致。"""
        v = ioco(SPEC_QUIET, CAND_RENAMED)
        self.assertTrue(v.conforms, msg=f"反例: {v.offending} after {v.trace}")

    def test_alarm_when_only_quiescence_allowed(self):
        """旧规程命令后只能静止而候选报警 => 不一致，最短历史 = 命令?。"""
        v = ioco(SPEC_QUIET, CAND_ALARM)
        self.assertFalse(v.conforms)
        self.assertEqual(v.trace, ["命令?"])
        self.assertIn("报警!", v.offending)
        self.assertEqual(v.spec_allowed_outputs, [Q])
        self.assertIn("报警!", v.candidate_outputs)
        self.assertNotIn("报警!", v.spec_allowed_outputs)
        # 逐步闭包：初始一步 + 命令一步
        self.assertEqual([s.kind for s in v.steps], ["initial", "input"])
        self.assertEqual(v.steps[1].cand_states, ["C1"])
        self.assertEqual(v.steps[1].spec_states, ["S1"])

    def test_unallowed_confirm_after_tau(self):
        """候选经静默 τ 后给出未允许的确认 => 不一致，闭包须含 τ 后状态。"""
        v = ioco(SPEC_QUIET, CAND_TAU_CONFIRM)
        self.assertFalse(v.conforms)
        self.assertEqual(v.trace, ["命令?"])
        self.assertEqual(v.offending, ["确认!"])
        self.assertEqual(v.spec_allowed_outputs, [Q])
        # 逐步闭包中候选状态集必须包含经静默可达的 C2
        self.assertEqual(v.steps[1].cand_states, ["C1", "C2"])
        self.assertEqual(v.steps[1].spec_states, ["S1"])

    def test_quiescence_offence(self):
        """旧规程必须持续报警、候选停滞只能静止 => δ 本身成为未允许输出。"""
        s = spec_payload(["S"], "S", [("S", "报警!", "S")])
        c = spec_payload(["C"], "C", [("C", Q, "C")])
        v = ioco(s, c)
        self.assertFalse(v.conforms)
        self.assertEqual(v.trace, [])
        self.assertEqual(v.offending, [Q])
        self.assertEqual(v.spec_allowed_outputs, ["报警!"])

    def test_fewer_outputs_is_allowed(self):
        """候选输出集合是旧规程子集（少报）在 ioco 下一致。"""
        s = spec_payload(["S0", "S1", "S2"], "S0",
                         [("S0", "命令?", "S1"), ("S0", "命令?", "S2"),
                          ("S1", "报警!", "S1"), ("S1", "确认!", "S1"),
                          ("S2", Q, "S2")])
        c = spec_payload(["C0", "C1"], "C0",
                         [("C0", "命令?", "C1"), ("C1", "报警!", "C1")])
        v = ioco(s, c)
        self.assertTrue(v.conforms)


class TauClosureTests(unittest.TestCase):

    def test_spec_tau_to_output_allows_it(self):
        """旧规程经静默可达报警位置时，候选直接报警应被允许。"""
        s = spec_payload(["S0", "S1", "S2"], "S0",
                         [("S0", "命令?", "S1"), ("S1", "静默", "S2"),
                          ("S2", "报警!", "S2")])
        c = spec_payload(["C0", "C1"], "C0",
                         [("C0", "命令?", "C1"), ("C1", "报警!", "C1")])
        v = ioco(s, c)
        self.assertTrue(v.conforms, msg=f"{v.offending} after {v.trace}")
        # 直接核对 τ 闭包：初始闭包只含 S0；命令后闭包含 S1、S2
        sp = parse_spec("旧", s)
        self.assertEqual(_tau_closure(sp, frozenset({sp.initial})), frozenset({"S0"}))
        self.assertEqual(
            _tau_closure(sp, frozenset({"S1"})), frozenset({"S1", "S2"}))

    def test_tau_chain_quiescence(self):
        """连续静默到停滞位置：两端都视为可观察静止，判一致。"""
        s = spec_payload(["S0", "S1", "S2"], "S0",
                         [("S0", "命令?", "S1"), ("S1", "静默", "S2")])
        c = spec_payload(["C0", "C1"], "C0",
                         [("C0", "命令?", "C1"), ("C1", Q, "C1")])
        v = ioco(s, c)
        self.assertTrue(v.conforms)
        sp = parse_spec("旧", s)
        # S1、S2（经静默到达的停滞位置）都必须可观察静止
        self.assertEqual(_tau_closure(sp, frozenset({"S1"})), frozenset({"S1", "S2"}))
        self.assertTrue({"S1", "S2"} <= sp.quiescent)

    def test_delta_self_loop_then_continue(self):
        """δ 是静止位置自环：观察静止后输入仍可执行。"""
        s = spec_payload(["S0", "S1"], "S0",
                         [("S0", Q, "S0"), ("S0", "命令?", "S1"),
                          ("S1", "报警!", "S1")])
        c = spec_payload(["C0", "C1"], "C0",
                         [("C0", Q, "C0"), ("C0", "命令?", "C1"),
                          ("C1", "报警!", "C1")])
        v = ioco(s, c)
        self.assertTrue(v.conforms)

        bad = spec_payload(["C0", "C1"], "C0",
                           [("C0", Q, "C0"), ("C0", "命令?", "C1"),
                            ("C1", Q, "C1")])
        v2 = ioco(s, bad)
        self.assertFalse(v2.conforms)
        self.assertEqual(v2.trace, ["命令?"])
        self.assertEqual(v2.offending, [Q])


    def test_delta_then_tau_progress(self):
        """δ 自环后再取 τ 闭包：静止位置经静默到达的位置仍可继续轨迹。"""
        # 旧规程：S1 显式静止，且有静默到 S2，S2 在 next? 后报警
        s = spec_payload(
            ["S0", "S1", "S2", "S3"], "S0",
            [("S0", "命令?", "S1"), ("S1", Q, "S1"), ("S1", "静默", "S2"),
             ("S2", "next?", "S3"), ("S3", "报警!", "S3")])
        c = spec_payload(
            ["C0", "C1", "C2", "C3"], "C0",
            [("C0", "命令?", "C1"), ("C1", Q, "C1"), ("C1", "静默", "C2"),
             ("C2", "next?", "C3"), ("C3", "报警!", "C3")])
        self.assertTrue(ioco(s, c).conforms)

        # 候选少了报警：命令? 后闭包已含经静默到达的 C2，
        # 故最短历史为 [命令?, next?]（不包含冗余的静止步）
        bad = spec_payload(
            ["C0", "C1", "C2", "C3"], "C0",
            [("C0", "命令?", "C1"), ("C1", Q, "C1"), ("C1", "静默", "C2"),
             ("C2", "next?", "C3"), ("C3", Q, "C3")])
        v = ioco(s, bad)
        self.assertFalse(v.conforms)
        self.assertEqual(v.trace, ["命令?", "next?"])
        self.assertEqual(v.offending, [Q])


class CycleAndShortestTests(unittest.TestCase):

    def test_cycles_terminate_and_still_conform(self):
        """带环自回放的等价规程必须终止判定并判一致（不得以有限枚举替代）。"""
        s = spec_payload(["S0", "S1"], "S0",
                         [("S0", "命令?", "S1"), ("S1", "完成!", "S0")])
        c = spec_payload(["X", "Y"], "X",
                         [("X", "命令?", "Y"), ("Y", "完成!", "X")])
        v = ioco(s, c)
        self.assertTrue(v.conforms)

    def test_shortest_trace_ascii_order(self):
        """多个反例时返回长度最短、并列时 ASCII 序最小的历史。"""
        # 旧规程：a? 后只许静止；b? 后也只许静止。
        # 候选：a? 后报警，b? 后报警；ASCII 下 "a?" < "b?"。
        s = spec_payload(["S0", "Sa", "Sb"], "S0",
                         [("S0", "a?", "Sa"), ("S0", "b?", "Sb"),
                          ("Sa", Q, "Sa"), ("Sb", Q, "Sb")])
        c = spec_payload(["C0", "Ca", "Cb"], "C0",
                         [("C0", "a?", "Ca"), ("C0", "b?", "Cb"),
                          ("Ca", "报警!", "Ca"), ("Cb", "报警!", "Cb")])
        v = ioco(s, c)
        self.assertFalse(v.conforms)
        self.assertEqual(v.trace, ["a?"])

    def test_longer_when_immediate_matches(self):
        """初始与第一步都允许时，反例在更深的历史处被找到。"""
        s = spec_payload(["S0", "S1", "S2"], "S0",
                         [("S0", "go?", "S1"), ("S1", "next?", "S2"),
                          ("S2", Q, "S2")])
        c = spec_payload(["C0", "C1", "C2"], "C0",
                         [("C0", "go?", "C1"), ("C1", "next?", "C2"),
                          ("C2", "报警!", "C2")])
        v = ioco(s, c)
        self.assertFalse(v.conforms)
        self.assertEqual(v.trace, ["go?", "next?"])
        self.assertEqual(len(v.steps), 3)


class ValidationTests(unittest.TestCase):

    def _expect(self, payload, fragment):
        with self.assertRaises(SpecError) as ctx:
            parse_spec("t", payload)
        self.assertIn(fragment, str(ctx.exception))

    def test_illegal_label(self):
        self._expect(spec_payload(["S"], "S", [("S", "报警", "S")]), "非法标签")

    def test_dangling_source_and_target(self):
        self._expect(spec_payload(["S"], "S", [("X", "报警!", "S")]), "悬空迁移")
        self._expect(spec_payload(["S"], "S", [("S", "报警!", "X")]), "悬空迁移")

    def test_missing_initial(self):
        self._expect({"locations": "S", "initial": "", "transitions": []}, "缺少初始位置")

    def test_initial_not_declared(self):
        self._expect({"locations": "S", "initial": "S0", "transitions": []}, "悬空初始位置")

    def test_duplicate_location(self):
        self._expect({"locations": "S,S", "initial": "S", "transitions": []},
                     "重复状态声明")

    def test_missing_locations(self):
        self._expect({"locations": "", "initial": "", "transitions": []}, "有限位置")

    def test_empty_label_with_endpoints(self):
        self._expect(spec_payload(["S"], "S", [("S", "  ", "S")]), "缺少输入/输出标签")

    def test_error_points_to_transition_index(self):
        with self.assertRaises(SpecError) as ctx:
            parse_spec("t", spec_payload(
                ["S"], "S", [("S", "ok?", "S"), ("S", "坏标签", "S")]))
        self.assertIn("第 2 条迁移", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
