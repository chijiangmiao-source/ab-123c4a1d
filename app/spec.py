"""有限状态 IOLTS 规程模型：解析、校验与 ioco 判定。

标签约定（输入输出名称互不重名，输入可由系统启用/禁用）：

* 迁移 "输入? -> 下一位置"        表示可观察输入
* 迁移 "确认! -> 下一位置"        表示可观察输出
* 迁移 "静默 -> 下一位置"（或 tau）表示内部不可见迁移
* 输出动作 "静止"（QUIESCENCE_LABEL）将当前位置显式标记为静止位置，
  在该位置可观察到 delta，与可观察静止输出 "静止" 等价。

判定遵循经典 ioco（Tretmans）：在所有由暂停轨迹（含 delta 的轨迹）
可达的状态集之后，实现给出的输出集合必须是规范允许输出集合的子集；
候选 ioco 旧规程 iff  out(cand after sigma) ⊆ out(spec after sigma)。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, FrozenSet, List, Optional, Set, Tuple

QUIESCENCE_LABEL = "静止"
TAU_LABELS = frozenset({"静默", "tau", "τ"})
INPUT_SUFFIX = "?"
OUTPUT_SUFFIX = "!"
OUTPUT_ACTION = "output"
INPUT_ACTION = "input"
QUIESCENCE_ACTION = "quiescence"
TAU = None  # 内部迁移在内部结构中以 None 表示

VALID_KINDS = (INPUT_ACTION, OUTPUT_ACTION, QUIESCENCE_ACTION)
KIND_CN = {
    INPUT_ACTION: "输入",
    OUTPUT_ACTION: "输出",
    QUIESCENCE_ACTION: "静止输出",
}


class SpecError(Exception):
    """单个规程的校验错误，message 为面向用户的中文描述。"""


@dataclass(frozen=True)
class LabeledTransition:
    source: str
    kind: str            # input / output / quiescence
    label: str           # 规范化后的可观察标签（静止为 "静止"）
    target: str


@dataclass
class ParsedSpec:
    name: str
    locations: List[str]
    initial: str
    transitions: List[LabeledTransition]
    # 位置 -> 标签种类集合（"静止" 输出声明）
    output_marks: Dict[str, Set[str]] = field(default_factory=dict)

    # 以下为派生结构
    out_edges: Dict[str, List[Tuple[str, str]]] = field(default_factory=dict)
    in_edges: Dict[str, List[Tuple[str, str]]] = field(default_factory=dict)
    tau_targets: Dict[str, List[str]] = field(default_factory=dict)
    quiescent: Set[str] = field(default_factory=set)


def _split_locations(raw: str) -> List[str]:
    return [part.strip() for part in raw.replace("，", ",").split(",") if part.strip()]


def _classify(action: str) -> Tuple[str, str]:
    """返回 (kind, 规范化标签)。"""
    a = action.strip()
    if a in TAU_LABELS:
        return "tau", ""
    if a == QUIESCENCE_LABEL:
        return QUIESCENCE_ACTION, QUIESCENCE_LABEL
    if a.endswith(OUTPUT_SUFFIX):
        label = a[:-1].strip()
        if not label:
            raise SpecError("输出标签不能为空（形如 报警!）")
        return OUTPUT_ACTION, label + OUTPUT_SUFFIX
    if a.endswith(INPUT_SUFFIX):
        label = a[:-1].strip()
        if not label:
            raise SpecError("输入标签不能为空（形如 命令?）")
        return INPUT_ACTION, label + INPUT_SUFFIX
    raise SpecError(
        f"非法标签 {a!r}：输入须以 '?' 结尾（如 命令?），输出须以 '!' 结尾"
        f"（如 报警!），内部迁移写作 '静默'，静止输出写作 '静止'"
    )


def parse_spec(name: str, payload: dict) -> ParsedSpec:
    """把前端提交的原始 dict 解析为经过全部校验的 ParsedSpec。

    payload 形如：
      {"locations": "S0,S1", "initial": "S0",
       "transitions": [{"from": "S0", "action": "cmd?", "to": "S1"}]}
    所有错误以 SpecError 抛出，信息带位置/序号以便定位。
    """
    who = f"规程[{name}]" if name else "规程"
    raw_locs = payload.get("locations", "")
    if not isinstance(raw_locs, str):
        raise SpecError(f"{who}：有限位置必须是逗号分隔的文本")
    locations = _split_locations(raw_locs)

    seen: Set[str] = set()
    duplicates: List[str] = []
    for loc in locations:
        if loc in seen:
            duplicates.append(loc)
        seen.add(loc)
    if duplicates:
        raise SpecError(
            f"{who}：同一标签下重复状态声明：" + "、".join(sorted(set(duplicates)))
        )
    if not locations:
        raise SpecError(f"{who}：缺少有限位置声明（至少需要一个位置）")

    initial = str(payload.get("initial", "")).strip()
    if not initial:
        raise SpecError(f"{who}：缺少初始位置")
    if initial not in seen:
        raise SpecError(
            f"{who}：初始位置 {initial!r} 不在有限位置 "
            f"{'、'.join(locations)} 中（悬空初始位置）"
        )

    raw_transitions = payload.get("transitions", [])
    if not isinstance(raw_transitions, list):
        raise SpecError(f"{who}：迁移列表格式不正确")

    transitions: List[LabeledTransition] = []
    output_marks: Dict[str, Set[str]] = {}

    for idx, item in enumerate(raw_transitions):
        pos = f"{who}第 {idx + 1} 条迁移"
        if not isinstance(item, dict):
            raise SpecError(f"{pos}：格式不正确")
        src = str(item.get("from", "")).strip()
        dst = str(item.get("to", "")).strip()
        action = str(item.get("action", "")).strip()
        if not action:
            # 空行（页面动态增删残留）直接忽略
            if not src and not dst:
                continue
            raise SpecError(f"{pos}：缺少输入/输出标签")
        if not src:
            raise SpecError(f"{pos}（标签 {action}）：缺少源位置")
        if not dst:
            raise SpecError(f"{pos}（标签 {action}）：缺少目标位置")
        if src not in seen:
            raise SpecError(
                f"{pos}：源位置 {src!r} 未在有限位置中声明（悬空迁移）"
            )
        if dst not in seen:
            raise SpecError(
                f"{pos}：目标位置 {dst!r} 未在有限位置中声明（悬空迁移）"
            )
        try:
            kind, label = _classify(action)
        except SpecError as exc:
            raise SpecError(f"{pos}：{exc}") from None
        if kind == "tau":
            transitions.append(LabeledTransition(src, "tau", "", dst))
            continue
        if kind == QUIESCENCE_ACTION:
            marks = output_marks.setdefault(src, set())
            if QUIESCENCE_LABEL in marks:
                raise SpecError(f"{pos}：位置 {src!r} 重复声明静止输出")
            marks.add(QUIESCENCE_LABEL)
            transitions.append(LabeledTransition(src, kind, label, src))
            continue
        transitions.append(LabeledTransition(src, kind, label, dst))
        if kind == OUTPUT_ACTION:
            output_marks.setdefault(src, set()).add(label)

    parsed = ParsedSpec(
        name=name,
        locations=locations,
        initial=initial,
        transitions=transitions,
        output_marks=output_marks,
    )
    _build_derived(parsed)
    return parsed


def _build_derived(p: ParsedSpec) -> None:
    """构造迁移邻接表，并按「显式静止 + 输出停滞」计算静止位置集合。

    没有任何输出（含 delta）可选的位置是停滞状态（deadlock），按 ioco
    语义同样可观察静止；若某位置能经 tau 到达停滞位置，它也是静止的。
    显式声明过输出或静止的位置永远不被推断为停滞（输出可被系统禁用，
    是否允许静止以工程师的显式标记为准）。
    """
    out_edges: Dict[str, List[Tuple[str, str]]] = {loc: [] for loc in p.locations}
    in_edges: Dict[str, List[Tuple[str, str]]] = {loc: [] for loc in p.locations}
    tau_targets: Dict[str, List[str]] = {loc: [] for loc in p.locations}
    quiescent: Set[str] = {
        loc for loc in p.locations if QUIESCENCE_LABEL in p.output_marks.get(loc, set())
    }

    for t in p.transitions:
        if t.kind == "tau":
            tau_targets[t.source].append(t.target)
        elif t.kind == OUTPUT_ACTION:
            out_edges[t.source].append((t.label, t.target))
        elif t.kind == INPUT_ACTION:
            in_edges[t.source].append((t.label, t.target))
        # quiescence 是自环语义标记，不进入邻接表

    # 静止位置 = 显式标记静止的位置 ∪ 不能经 τ* 到达任何真实输出的位置
    # （仅有输入边的位置在输入被环境禁用时同样停滞，可观察 δ）。
    can_output: Set[str] = {loc for loc in p.locations if out_edges[loc]}
    changed = True
    while changed:
        changed = False
        for loc in p.locations:
            if loc in can_output:
                continue
            if any(tgt in can_output for tgt in tau_targets[loc]):
                can_output.add(loc)
                changed = True
    for loc in p.locations:
        if loc in quiescent or loc not in can_output:
            quiescent.add(loc)

    p.out_edges = out_edges
    p.in_edges = in_edges
    p.tau_targets = tau_targets
    p.quiescent = quiescent


# --------------------------------------------------------------------------- #
# ioco 判定
# --------------------------------------------------------------------------- #


@dataclass
class ClosureStep:
    """逐步闭包展示中的一步。"""

    label: str                       # 本步观察到的标签（首步为初始）
    kind: str                        # initial / input / output / quiescence
    spec_states: List[str]           # 该步之后旧规程闭包状态集
    cand_states: List[str]           # 该步之后候选闭包状态集


@dataclass
class IocoVerdict:
    conforms: bool
    trace: List[str]                  # 最短反例轨迹（含 delta 标签）
    steps: List[ClosureStep]
    candidate_outputs: List[str]      # 反例处候选可给出的输出
    spec_allowed_outputs: List[str]   # 反例处旧规程允许的输出
    offending: List[str]              # 候选有而旧规程不允许的输出
    spec_quiescent_states: List[str] = field(default_factory=list)
    cand_quiescent_states: List[str] = field(default_factory=list)


def _tau_closure(p: ParsedSpec, states: FrozenSet[str]) -> FrozenSet[str]:
    result = set(states)
    stack = list(states)
    while stack:
        s = stack.pop()
        for tgt in p.tau_targets.get(s, ()):  # noqa: PERF401 - 顺序无关
            if tgt not in result:
                result.add(tgt)
                stack.append(tgt)
    return frozenset(result)


def _after_delta(p: ParsedSpec, states: FrozenSet[str]) -> FrozenSet[str]:
    """观察静止（delta）之后的状态集。

    delta 是静止位置上的自环；自环后仍需取 τ 闭包——静止位置可能经
    内部静默到达活跃位置，观察到静止并不排除随后的内部进展与输出。
    """
    quiet = frozenset(s for s in states if s in p.quiescent)
    return _tau_closure(p, quiet)


def _out(p: ParsedSpec, states: FrozenSet[str]) -> Set[str]:
    """out(S)：状态集 S（已闭包）可给出的全部输出，含 delta。"""
    result: Set[str] = set()
    for s in states:
        result.update(label for label, _ in p.out_edges.get(s, ()))
        if s in p.quiescent:
            result.add(QUIESCENCE_LABEL)
    return result


def _step(p: ParsedSpec, states: FrozenSet[str], label: str) -> FrozenSet[str]:
    """已闭包状态集上观察 label（输入、输出或 delta）后的闭包状态集。"""
    if label == QUIESCENCE_LABEL:
        return _after_delta(p, states)
    edges = p.in_edges if label.endswith(INPUT_SUFFIX) else p.out_edges
    nxt: Set[str] = set()
    for s in states:
        for lab, tgt in edges.get(s, ()):
            if lab == label:
                nxt.add(tgt)
    return _tau_closure(p, frozenset(nxt))


def _sorted_states(states: FrozenSet[str]) -> List[str]:
    return sorted(states)


def check_ioco(spec: ParsedSpec, cand: ParsedSpec) -> IocoVerdict:
    """判定 cand ioco spec，返回判定与最短（ASCII 序）反例证据。

    反例 = 暂停轨迹 σ（对双方都可执行）之后，候选存在旧规程不允许的
    输出。按轨迹长度 BFS；同一深度按标签 ASCII 序展开，保证得到的是
    ASCII 顺序下确定的最短历史。
    """
    spec0 = _tau_closure(spec, frozenset({spec.initial}))
    cand0 = _tau_closure(cand, frozenset({cand.initial}))

    initial_step = ClosureStep(
        label="",
        kind="initial",
        spec_states=_sorted_states(spec0),
        cand_states=_sorted_states(cand0),
    )

    # 公共标签宇宙：暂停轨迹可由输入、输出、delta 组成；只可能沿双方
    # 共有的可观察动作延伸（单方动作不会让两个 after 集都非空）。
    spec_ins = {lab for ls in spec.in_edges.values() for lab, _ in ls}
    cand_ins = {lab for ls in cand.in_edges.values() for lab, _ in ls}
    spec_outs = {lab for ls in spec.out_edges.values() for lab, _ in ls}
    cand_outs = {lab for ls in cand.out_edges.values() for lab, _ in ls}
    shared = (spec_ins & cand_ins) | (spec_outs & cand_outs)
    universe = sorted(shared | {QUIESCENCE_LABEL})

    # BFS 节点：(轨迹, spec闭包集, cand闭包集, 逐步记录)
    queue: List[Tuple[Tuple[str, ...], FrozenSet[str], FrozenSet[str],
                      List[ClosureStep]]] = [
        ((), spec0, cand0, [initial_step])
    ]
    # (旧规程集, 候选集) 对有限，首次按 BFS + ASCII 序到达即为该对的
    # ASCII 序最短历史；剪枝同时消除迁移环带来的无限展开。
    visited: Set[Tuple[FrozenSet[str], FrozenSet[str]]] = {(spec0, cand0)}
    head = 0
    while head < len(queue):
        trace, ss, cs, steps = queue[head]
        head += 1

        cand_out = _out(cand, cs)
        spec_out = _out(spec, ss)
        offending = cand_out - spec_out
        if offending:
            return IocoVerdict(
                conforms=False,
                trace=list(trace),
                steps=steps,
                candidate_outputs=sorted(cand_out),
                spec_allowed_outputs=sorted(spec_out),
                offending=sorted(offending),
                spec_quiescent_states=sorted(ss & spec.quiescent),
                cand_quiescent_states=sorted(cs & cand.quiescent),
            )

        # 沿双方都可执行的下一观察延伸；ASCII 序由 universe 排序保证
        for label in universe:
            ss2 = _step(spec, ss, label)
            if not ss2:
                continue
            cs2 = _step(cand, cs, label)
            if not cs2:
                continue
            if (ss2, cs2) in visited:
                continue
            visited.add((ss2, cs2))
            kind = (
                "quiescence" if label == QUIESCENCE_LABEL
                else "input" if label.endswith(INPUT_SUFFIX)
                else "output"
            )
            queue.append((
                trace + (label,),
                ss2,
                cs2,
                steps + [ClosureStep(
                    label=label,
                    kind=kind,
                    spec_states=_sorted_states(ss2),
                    cand_states=_sorted_states(cs2),
                )],
            ))

    return IocoVerdict(
        conforms=True,
        trace=[],
        steps=[initial_step],
        candidate_outputs=sorted(_out(cand, cand0)),
        spec_allowed_outputs=sorted(_out(spec, spec0)),
        offending=[],
        spec_quiescent_states=sorted(spec0 & spec.quiescent),
        cand_quiescent_states=sorted(cand0 & cand.quiescent),
    )
