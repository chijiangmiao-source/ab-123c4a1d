/* 束线联锁规程 ioco 复核前端：仅通过真实 HTTP 接口提交与读取结论。 */
"use strict";

const PRESETS = {
  rename: {
    spec: {
      name: "旧规程",
      locations: "S0,S1",
      initial: "S0",
      transitions: [
        { from: "S0", action: "命令?", to: "S1" },
        { from: "S1", action: "静止", to: "S1" }
      ]
    },
    candidate: {
      name: "候选规程",
      locations: "待命,执行",
      initial: "待命",
      transitions: [
        { from: "待命", action: "命令?", to: "执行" },
        { from: "执行", action: "静止", to: "执行" }
      ]
    }
  },
  alarm: {
    spec: {
      name: "旧规程",
      locations: "S0,S1",
      initial: "S0",
      transitions: [
        { from: "S0", action: "命令?", to: "S1" },
        { from: "S1", action: "静止", to: "S1" }
      ]
    },
    candidate: {
      name: "候选规程",
      locations: "C0,C1",
      initial: "C0",
      transitions: [
        { from: "C0", action: "命令?", to: "C1" },
        { from: "C1", action: "报警!", to: "C1" }
      ]
    }
  },
  tau: {
    spec: {
      name: "旧规程",
      locations: "S0,S1",
      initial: "S0",
      transitions: [
        { from: "S0", action: "命令?", to: "S1" },
        { from: "S1", action: "静止", to: "S1" }
      ]
    },
    candidate: {
      name: "候选规程",
      locations: "C0,C1,C2",
      initial: "C0",
      transitions: [
        { from: "C0", action: "命令?", to: "C1" },
        { from: "C1", action: "静默", to: "C2" },
        { from: "C2", action: "确认!", to: "C2" }
      ]
    }
  }
};

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else if (k === "html") node.innerHTML = v;
    else node.setAttribute(k, v);
  }
  for (const child of children) {
    if (child == null) continue;
    node.appendChild(typeof child === "string" ? document.createTextNode(child) : child);
  }
  return node;
}

function buildEditor(container, sideName) {
  const locInput = el("input", { type: "text", placeholder: "逗号分隔，如 S0,S1,S2" });
  const initInput = el("input", { type: "text", placeholder: "初始位置，如 S0" });
  const tbody = el("tbody");

  function addRow(t = { from: "", action: "", to: "" }) {
    const fromIn = el("input", { type: "text", placeholder: "源位置" });
    const actIn = el("input", { type: "text", placeholder: "命令? / 报警! / 静默 / 静止" });
    const toIn = el("input", { type: "text", placeholder: "目标位置" });
    fromIn.value = t.from || "";
    actIn.value = t.action || "";
    toIn.value = t.to || "";
    const del = el("button", { class: "del", type: "button", title: "删除该行" }, "✕");
    const row = el("tr", {},
      el("td", {}, fromIn), el("td", {}, actIn), el("td", {}, toIn),
      el("td", {}, del));
    del.addEventListener("click", () => row.remove());
    tbody.appendChild(row);
  }

  container.appendChild(el("label", {}, "有限位置"));
  container.appendChild(locInput);
  container.appendChild(el("label", {}, "初始位置"));
  container.appendChild(initInput);
  container.appendChild(el("label", {}, "迁移（输入命令 / 输出标签 / 静默）"));
  container.appendChild(el("table", { class: "trans" },
    el("thead", {}, el("tr", {},
      el("th", {}, "源位置"), el("th", {}, "输入或输出标签"),
      el("th", {}, "目标位置"), el("th", { style: "width:32px" }))),
    tbody));
  container.appendChild(el("button", { class: "rowbtn", type: "button" }, "+ 添加迁移"))
    .addEventListener("click", () => addRow());

  addRow();
  addRow();

  return {
    load(data) {
      locInput.value = data.locations || "";
      initInput.value = data.initial || "";
      tbody.innerHTML = "";
      (data.transitions || []).forEach(addRow);
      if (!tbody.children.length) addRow();
    },
    collect() {
      return {
        name: sideName,
        locations: locInput.value,
        initial: initInput.value,
        transitions: [...tbody.querySelectorAll("tr")].map((tr) => {
          const ins = tr.querySelectorAll("input");
          return { from: ins[0].value.trim(), action: ins[1].value.trim(),
                   to: ins[2].value.trim() };
        })
      };
    }
  };
}

const editors = {
  spec: buildEditor(document.querySelector('[data-editor="spec"]'), "旧规程"),
  candidate: buildEditor(document.querySelector('[data-editor="candidate"]'), "候选规程")
};

editors.spec.load(PRESETS.alarm.spec);
editors.candidate.load(PRESETS.alarm.candidate);

document.querySelectorAll(".preset").forEach((btn) => {
  btn.addEventListener("click", () => {
    const p = PRESETS[btn.dataset.preset];
    editors.spec.load(p.spec);
    editors.candidate.load(p.candidate);
    renderPending();
  });
});

const resultBox = document.getElementById("result");
const submitBtn = document.getElementById("submit-btn");

function renderPending() {
  resultBox.innerHTML = "";
  resultBox.appendChild(el("div", { class: "evbox" },
    "已清除先前结论，等待提交后读取接口复核结论……"));
}

function renderErrors(errors) {
  const ul = el("ul");
  for (const e of errors) {
    ul.appendChild(el("li", {},
      el("span", { class: "err-side" }, e.side === "spec" ? "旧规程：" : "候选规程："),
      e.message));
  }
  resultBox.innerHTML = "";
  resultBox.appendChild(el("div", { class: "errors" },
    el("h3", {}, "录入校验未通过（先前结论已清除，未执行一致性判定）"), ul));
}

function kindClass(kind) {
  return "tag-io-" + kind;
}

function outputPill(label, cls) {
  return el("span", { class: "out-pill " + cls }, label);
}

function renderVerdict(data) {
  const ok = data.verdict === "consistent";
  const q = data.quiescence_label;
  const box = el("div", { class: "verdict " + (ok ? "ok" : "bad") });
  box.appendChild(el("h3", {},
    ok ? "复核结论：一致（候选 ioco 旧规程）"
       : "复核结论：不一致（候选 NOT ioco 旧规程）"));

  if (!ok) {
    box.appendChild(el("p", { style: "margin:4px 0 0" },
      "候选在旧规程可执行历史之后给出了旧规程不允许的输出；"
      + "下方为按 ASCII 顺序确定的最短反例历史。"));
  } else {
    box.appendChild(el("p", { style: "margin:4px 0 0" },
      "在每条双方可执行的暂停轨迹（含内部静默闭包与可观察静止）之后，"
      + "候选输出集合均为旧规程允许输出集合的子集。"));
  }

  const ev = el("div", { class: "evbox" });

  // 最短历史
  ev.appendChild(el("h4", {}, "最短历史（暂停轨迹，按 ASCII 序最短）"));
  if (!ok && data.trace.length) {
    const trace = el("p", { class: "trace" });
    trace.appendChild(el("span", { class: "step" }, "初始"));
    data.trace.forEach((lab) => {
      trace.appendChild(el("span", { class: "arrow" }, "→"));
      trace.appendChild(el("span", { class: "step " + kindClass(
        lab === q ? "quiescence" : lab.endsWith("?") ? "input" : "output") }, lab));
    });
    ev.appendChild(trace);
  } else {
    ev.appendChild(el("p", { class: "empty" }, ok ? "（无反例轨迹）" : "（空轨迹即反例）"));
  }

  // 输出对比
  ev.appendChild(el("h4", {}, "反例历史之后的输出对比"));
  const outs = el("div", { style: "display:grid;grid-template-columns:1fr 1fr;gap:10px" });
  const specOuts = new Set(data.spec_allowed_outputs);
  const candWrap = el("div", {}, el("div", { class: "hint", style: "margin-bottom:4px" },
    "候选可能给出的输出"));
  const candPills = el("div", { class: "outs" });
  for (const o of data.candidate_outputs) {
    candPills.appendChild(outputPill(o,
      specOuts.has(o) ? "out-cand" : "out-deny"));
  }
  if (!data.candidate_outputs.length) candPills.appendChild(el("span", { class: "empty" }, "（无）"));
  candWrap.appendChild(candPills);
  const specWrap = el("div", {}, el("div", { class: "hint", style: "margin-bottom:4px" },
    "旧规程允许的输出"));
  const specPills = el("div", { class: "outs" });
  for (const o of data.spec_allowed_outputs) specPills.appendChild(outputPill(o, "out-allow"));
  if (!data.spec_allowed_outputs.length) {
    specPills.appendChild(el("span", { class: "empty" }, "（无，连静止也不允许）"));
  }
  specWrap.appendChild(specPills);
  outs.appendChild(candWrap);
  outs.appendChild(specWrap);
  ev.appendChild(outs);
  if (!ok && data.offending_outputs.length) {
    ev.appendChild(el("p", { style: "margin:8px 0 0" },
      "未允许输出：", ...data.offending_outputs.map((o, i) =>
        outputPill(o, "out-deny"))));
  }

  // 逐步闭包
  ev.appendChild(el("h4", {}, "两侧逐步闭包状态集（含经静默 τ 到达的状态）"));
  const table = el("table", { class: "steps" });
  table.appendChild(el("thead", {}, el("tr", {},
    el("th", { style: "width:42px" }, "#"),
    el("th", { style: "width:150px" }, "本步观察"),
    el("th", {}, "旧规程闭包状态集"),
    el("th", {}, "候选闭包状态集"))));
  const tb = el("tbody");
  data.steps.forEach((s, i) => {
    const lab = s.kind === "initial"
      ? el("span", { class: "empty" }, "初始闭包")
      : el("span", { class: kindClass(s.kind) }, s.label);
    tb.appendChild(el("tr", {},
      el("td", {}, String(i)),
      el("td", {}, lab),
      el("td", { class: "states" }, s.spec_states.join(", ") || "∅"),
      el("td", { class: "states" }, s.candidate_states.join(", ") || "∅")));
  });
  table.appendChild(tb);
  ev.appendChild(table);

  resultBox.innerHTML = "";
  resultBox.appendChild(box);
  resultBox.appendChild(ev);
}

submitBtn.addEventListener("click", async () => {
  submitBtn.disabled = true;
  renderPending();
  try {
    const resp = await fetch("/api/verify", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        spec: editors.spec.collect(),
        candidate: editors.candidate.collect()
      })
    });
    const data = await resp.json();
    if (resp.ok && data.ok) renderVerdict(data);
    else renderErrors(data.errors || [{ side: "spec", message: "接口返回了无法识别的响应" }]);
  } catch (err) {
    renderErrors([{ side: "spec", message: "接口请求失败：" + err.message }]);
  } finally {
    submitBtn.disabled = false;
  }
});
