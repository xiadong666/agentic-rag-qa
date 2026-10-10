/* Agentic RAG 前端逻辑：无框架，原生 fetch + ReadableStream 解析 SSE

   与朴素 RAG 前端的区别只有两点：
     ① 请求带 agent 开关（可在页面上实时切换两条链路做对比）；
     ② 多了 traceList —— 把 Agent 的每一步（plan/tool/grade/reflect/verify）
        实时渲染成推理轨迹。**"过程可见"是 Agent 产品化的前提**：
        用户看到它检索了什么、判定为什么说不足，才会信任最终答案。
*/
const $ = (id) => document.getElementById(id);

const fileInput = $("fileInput"), uploadBtn = $("uploadBtn");
const docList = $("docList"), chatBox = $("chatBox");
const questionInput = $("questionInput"), sendBtn = $("sendBtn");
const sourceList = $("sourceList"), citeCount = $("citeCount");
const traceList = $("traceList"), traceCount = $("traceCount");
const agentToggle = $("agentToggle");

let sessionId = "demo-session";      // 简化演示：固定一个会话
let sourcesCache = [];               // 当前回答的来源
let streaming = false;

const STEP_ICON = {
  plan: "🧭", act: "🔧", grade: "⚖️", reflect: "🔄", verify: "🛡️", answer: "✍️", error: "⚠️",
};

/* ---------- 工具 ---------- */
async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.detail || `HTTP ${res.status}`);
  return body;
}

function esc(s) {
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

/* 极简 Markdown：代码、加粗、换行（够演示用；生产可引入 marked） */
function renderMd(text) {
  return esc(text)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>")
    .replace(/\[(\d+)\]/g, '<b class="cite">[$1]</b>')
    .replace(/\n/g, "<br/>");
}

function addMsg(role, html) {
  const div = document.createElement("div");
  div.className = `msg ${role}`;
  div.innerHTML = html;
  chatBox.appendChild(div);
  chatBox.scrollTop = chatBox.scrollHeight;
  return div;
}

function renderSources() {
  sourceList.innerHTML = "";
  citeCount.textContent = sourcesCache.length ? `（${sourcesCache.length} 条）` : "";
  sourcesCache.forEach((s) => {
    const li = document.createElement("li");
    li.title = "点击高亮该来源（演示：滚动到对话）";
    const page = s.page ? ` · 第${s.page}页` : "";
    li.innerHTML =
      `<div class="src-title">[${s.cite_index}] ${esc(s.doc_title)}${page}</div>` +
      `<div class="src-snippet">${esc(s.snippet)}</div>` +
      `<div class="src-score">score: ${s.score}</div>`;
    li.onclick = () => {
      chatBox.scrollTop = chatBox.scrollHeight;
    };
    sourceList.appendChild(li);
  });
}

/* ---------- Agent 推理轨迹 ---------- */
function resetTrace() {
  traceList.innerHTML = "";
  traceCount.textContent = "";
}

function addTrace(step) {
  const kind = step.kind || "act";
  const li = document.createElement("li");
  li.className = `trace-item trace-${kind}`;
  const cost = step.elapsed_ms ? `<span class="trace-time">${step.elapsed_ms}ms</span>` : "";
  li.innerHTML =
    `<div class="trace-title">${STEP_ICON[kind] || "•"} ${esc(step.title || kind)}${cost}</div>` +
    (step.detail ? `<div class="trace-detail">${esc(step.detail)}</div>` : "");
  traceList.appendChild(li);
  traceCount.textContent = `（${traceList.children.length} 步）`;
  traceList.scrollTop = traceList.scrollHeight;
}

/* ---------- 文档管理 ---------- */
async function refreshDocs() {
  const docs = await api("/api/documents");
  docList.innerHTML = "";
  if (!docs.length) {
    docList.innerHTML = "<li class='hint'>知识库还是空的</li>";
    return;
  }
  docs.forEach((d) => {
    const li = document.createElement("li");
    li.innerHTML =
      `<div><b>${esc(d.title)}</b><div class="meta">${d.chunk_count} 块 · ${esc(d.filename)}</div></div>` +
      `<button class="del" title="删除">🗑</button>`;
    li.querySelector(".del").onclick = async () => {
      await api(`/api/documents/${d.doc_id}`, { method: "DELETE" });
      refreshDocs();
    };
    docList.appendChild(li);
  });
}

async function uploadFiles() {
  const files = [...fileInput.files];
  if (!files.length) return;
  uploadBtn.disabled = true;
  for (const f of files) {
    const form = new FormData();
    form.append("file", f);
    const res = await fetch("/api/documents/upload", { method: "POST", body: form });
    const body = await res.json().catch(() => ({}));
    addMsg("system", res.ok
      ? `✅ 已入库《${esc(body.title)}》：${body.chunk_count} 个分块（${body.elapsed_ms}ms）`
      : `❌ 《${esc(f.name)}》失败：${esc(body.detail || res.status)}`);
  }
  fileInput.value = "";
  uploadBtn.disabled = false;
  refreshDocs();
}

/* ---------- 问答（SSE 流式） ---------- */
async function sendQuestion() {
  const q = questionInput.value.trim();
  if (!q || streaming) return;
  streaming = true;
  sendBtn.disabled = true;
  questionInput.value = "";
  addMsg("user", renderMd(q));

  const answerDiv = addMsg("assistant", "…");
  const useAgent = agentToggle.checked;
  sourcesCache = [];
  renderSources();
  resetTrace();
  if (!useAgent) addTrace({ kind: "plan", title: "朴素 RAG 链路（未启用 Agent 编排）" });

  try {
    const res = await fetch("/api/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        question: q, session_id: sessionId, use_history: true, agent: useAgent,
      }),
    });
    if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`);
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";
    let answerText = "";
    let sawToken = false;
    let sawError = false;
    let footer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      // SSE 事件按 \n\n 分隔
      const parts = buf.split("\n\n");
      buf = parts.pop() || "";
      for (const part of parts) {
        if (!part.startsWith("data:")) continue;
        const data = part.slice(5).trim();
        if (!data) continue;
        const evt = JSON.parse(data);
        const d = evt.data || {};

        if (evt.type === "meta") {
          // 朴素链路：一开始就把来源给出
          sourcesCache = d.sources || [];
          sessionId = d.session_id || sessionId;
          renderSources();
          if (d.rewritten_question && d.rewritten_question !== q) {
            addTrace({ kind: "reflect", title: "问题改写为独立问题", detail: d.rewritten_question });
          }
        } else if (evt.type === "plan") {
          addTrace(d);
          sessionId = (d.observation && d.observation.session_id) || sessionId;
        } else if (["tool", "grade", "reflect"].includes(evt.type)) {
          addTrace(d);
        } else if (evt.type === "token") {
          sawToken = true;
          answerText += d.text;
          answerDiv.className = "msg assistant";
          answerDiv.innerHTML = renderMd(answerText) + footer;
          chatBox.scrollTop = chatBox.scrollHeight;
        } else if (evt.type === "verify") {
          addTrace(d);
          const obs = d.observation || {};
          if (obs.grounded === false) {
            addTrace({
              kind: "error",
              title: "忠实度自检未通过，已追加提示",
              detail: (obs.unsupported || []).join("；") || d.detail,
            });
          }
        } else if (evt.type === "final") {
          // 最终事件里带完整契约：来源、用量、Agent 摘要
          sourcesCache = d.sources || [];
          renderSources();
          const u = d.usage || {};
          const ag = d.agent || {};
          const bits = [`耗时 ${d.elapsed_ms}ms`];
          if (u.llm_calls != null) bits.push(`${u.llm_calls} 次模型调用`);
          if (u.cost != null) bits.push(`成本 ¥${Number(u.cost).toFixed(6)}`);
          if (ag.rounds) bits.push(`检索 ${ag.rounds} 轮`);
          if (ag.stop_reason) bits.push(`停止原因 ${ag.stop_reason}`);
          if (ag.verdict) bits.push(`校验 ${ag.verdict === "grounded" ? "通过" : ag.verdict}`);
          footer = `<div class="hint">（${esc(bits.join(" · "))}）</div>`;
          if (ag.memo && ag.memo.conclusion) {
            answerText += `\n\n【决策备忘录】${ag.memo.conclusion}`;
          }
          answerDiv.innerHTML = renderMd(answerText) + footer;
        } else if (evt.type === "error") {
          sawError = true;
          answerDiv.className = "msg error";
          answerDiv.innerHTML = `⚠️ ${renderMd(d.message)}`;
        } else if (evt.type === "done" && d.elapsed_ms != null) {
          answerDiv.innerHTML = renderMd(answerText) + footer;
        }
      }
    }
    if (!sawError && !answerText) {
      // 确实没有任何输出且后端没报错时才显示兜底提示
      answerDiv.innerHTML = "（无输出：请查看右侧引用来源与后端日志）";
    } else if (!sawError && answerText && !sawToken) {
      answerDiv.innerHTML = renderMd(answerText) + `<div class="hint">（空回答）</div>`;
    }
  } catch (e) {
    answerDiv.className = "msg error";
    answerDiv.innerHTML = `⚠️ ${esc(e.message)}`;
  } finally {
    streaming = false;
    sendBtn.disabled = false;
  }
}

/* ---------- 事件绑定 & 启动 ---------- */
uploadBtn.onclick = uploadFiles;
sendBtn.onclick = sendQuestion;
questionInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendQuestion(); }
});

(async function init() {
  try {
    const h = await api("/health");
    $("statusDot").className = "status ok";
    $("statusText").textContent =
      `运行中 · ${h.chunks} 个分块 · LLM ${h.llm_ready ? "已配置" : "未配置(仅检索)"}`;
    // Agent 开关的默认状态跟随后端配置（前端只是"可视化这个开关"）
    if (h.agent && typeof h.agent.enabled === "boolean") agentToggle.checked = h.agent.enabled;
  } catch (e) {
    $("statusDot").className = "status err";
    $("statusText").textContent = "后端不可用";
  }
  refreshDocs();
})();
