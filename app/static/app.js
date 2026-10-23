// 유튜브 댓글 에이전트 — 대시보드 화면 동작
const $ = (id) => document.getElementById(id);

const state = {
  tab: "latest",
  sort: "comments", // 최신 영상 탭 정렬: comments(댓글 많은 순) | date(최신순)
  videos: [],
  selected: null,   // 선택한 영상
  draft: null,      // AI 초안
  problems: [],     // 현재 초안 검사 결과
  status: null,     // 서버 상태 (오늘 게시 수, 프로필 등)
  job: null,        // 진행 중인 게시 작업
  drafting: false,
};

// ---------- 공통 ----------
async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const d = data.detail;
    const err = new Error(typeof d === "string" ? d : d?.message || "요청에 실패했어요.");
    err.problems = d?.problems || [];
    throw err;
  }
  return data;
}

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else if (v !== undefined && v !== null && v !== false) node.setAttribute(k, v);
  }
  for (const c of children.flat()) {
    if (c === null || c === undefined || c === false) continue;
    node.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return node;
}

function normalize(text) {
  return (text || "").replace(/\s+/g, " ").trim();
}

function ago(iso) {
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff < 3600) return `${Math.max(1, Math.round(diff / 60))}분 전`;
  if (diff < 86400) return `${Math.round(diff / 3600)}시간 전`;
  if (diff < 86400 * 30) return `${Math.round(diff / 86400)}일 전`;
  return new Date(iso).toLocaleDateString("ko-KR");
}

function fmtDate(iso) {
  const d = new Date(iso);
  return `${d.getFullYear()}.${String(d.getMonth() + 1).padStart(2, "0")}.${String(d.getDate()).padStart(2, "0")}`;
}

function fmtTime(iso) {
  const d = new Date(iso);
  const p = (n) => String(n).padStart(2, "0");
  return `${p(d.getMonth() + 1)}.${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

const num = (n) => Number(n || 0).toLocaleString("ko-KR");

// ---------- 상태 ----------
async function loadStatus() {
  state.status = await api("/api/status");
  const s = state.status;
  $("today").textContent = s.today;
  $("limit").textContent = s.limit;
  $("today").parentElement.classList.toggle("full", s.today >= s.limit);
  renderProfiles();
  renderSetup();
  updatePostButton();
  // 누르기 전에도 어떤 순서로 진행되는지 보이게 한다.
  if (!state.job && !$("steps").children.length) renderSteps({ state: "idle", step: null, progress: 0 });
}

function renderProfiles() {
  const sel = $("profile");
  const prev = sel.value || "auto";
  sel.replaceChildren(el("option", { value: "auto" }, "자동 배정 (돌아가며)"));
  for (const p of state.status.profiles) {
    sel.append(el("option", { value: p.name, disabled: !p.ready }, p.ready ? p.name : `${p.name} (로그인 필요)`));
  }
  sel.value = [...sel.options].some((o) => o.value === prev && !o.disabled) ? prev : "auto";
}

function renderSetup() {
  const s = state.status;
  const items = [];
  if (!s.keys.youtube) items.push(el("li", {}, ".env 에 ", el("code", {}, "YOUTUBE_API_KEY"), " 를 넣어 주세요 (영상 불러오기에 필요)."));
  if (!s.keys.anthropic) items.push(el("li", {}, ".env 에 ", el("code", {}, "ANTHROPIC_API_KEY"), " 를 넣어 주세요 (댓글 초안에 필요)."));
  if (!s.profiles.some((p) => p.ready)) {
    items.push(el("li", {}, "로그인된 크롬 프로필이 없어요. 터미널에서 ",
      el("code", {}, `python scripts/open_profile.py ${s.profiles[0]?.name || "유튜브1"}`), " 실행 후 로그인해 주세요."));
  }
  const box = $("setup");
  box.hidden = items.length === 0;
  box.replaceChildren(el("strong", {}, "시작 전 준비가 필요해요"), el("ul", {}, items));
}

// ---------- ① 영상 불러오기 ----------
function setTab(tab) {
  state.tab = tab;
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === tab));
  $("load").textContent = tab === "latest" ? "영상 불러오기" : "뜨기 직전 영상 찾기";
  $("list-note").textContent = tab === "rising"
    ? "조회수 1,000~5,000 · 시간당 조회수 150 이상인 최근 영상이에요. 초안까지만 만들어요."
    : "";
  state.videos = [];
  $("sort").hidden = true;
  renderList();
}

function sortVideos() {
  if (state.tab !== "latest") return; // 뜨기 직전 탭은 시간당 조회수 순 그대로
  const key = state.sort === "date"
    ? (v) => new Date(v.published_at).getTime()
    : (v) => v.comment_count || 0;
  state.videos.sort((a, b) => key(b) - key(a));
}

function setSort(sort) {
  state.sort = sort;
  document.querySelectorAll("#sort button").forEach((b) => b.classList.toggle("active", b.dataset.sort === sort));
  sortVideos();
  renderList();
}

async function loadVideos() {
  const btn = $("load");
  btn.disabled = true;
  const label = btn.textContent;
  btn.textContent = "불러오는 중…";
  try {
    // 5분 안에 다시 누르면 서버에 저장된 목록을 보여준다 (YouTube API 할당량 절약)
    const path = state.tab === "latest" ? "/api/videos" : "/api/videos/rising";
    const { videos } = await api(path);
    state.videos = videos.map((v) => ({ ...v, source: state.tab }));
    sortVideos();
    $("list-note").textContent = videos.length
      ? `${videos.length}개 영상` + (state.tab === "rising" ? " · 초안까지만 만들어요" : "")
      : (state.tab === "rising" ? "지금은 조건에 맞는 영상이 없어요." : "영상이 없어요.");
    $("sort").hidden = state.tab !== "latest" || videos.length === 0;
    renderList();
  } catch (e) {
    $("list-note").textContent = e.message;
  } finally {
    btn.disabled = false;
    btn.textContent = label;
  }
}

async function openUrl(ev) {
  ev.preventDefault();
  const url = $("url-input").value.trim();
  if (!url) return;
  try {
    const { video } = await api("/api/videos/by-url", { method: "POST", body: { url } });
    const v = { ...video, source: "url" };
    state.videos = [v, ...state.videos.filter((x) => x.id !== v.id)];
    $("url-input").value = "";
    renderList();
    selectVideo(v);
  } catch (e) {
    $("list-note").textContent = e.message;
  }
}

function renderList() {
  const list = $("video-list");
  list.replaceChildren(...state.videos.map((v) =>
    el("li", {},
      el("button", {
        class: "video" + (state.selected?.id === v.id ? " selected" : ""),
        onclick: () => selectVideo(v),
      },
        el("img", { src: v.thumbnail, alt: "", loading: "lazy" }),
        el("div", {},
          el("div", { class: "v-title", title: v.title }, v.title),
          el("div", { class: "v-meta" }, `${v.channel} · ${ago(v.published_at)} · 댓글 ${num(v.comment_count)}`),
          v.source === "rising" ? el("span", { class: "tag rise" }, `조회수 ${num(v.view_count)} · 시간당 ${num(v.views_per_hour)}`) : null,
          v.source === "url" ? el("span", { class: "tag rise" }, "링크로 추가") : null,
          v.commented ? el("span", { class: "tag done" }, "댓글 완료") : null,
        ),
      ),
    ),
  ));
}

// ---------- ② 영상 선택 → 초안 ----------
async function selectVideo(v, regenerate = false) {
  state.selected = v;
  state.draft = null;
  state.problems = [];
  renderList();
  $("draft-empty").hidden = true;
  $("draft").hidden = true;
  $("draft-error").hidden = true;
  $("draft-loading").hidden = false;
  state.drafting = true;
  updatePostButton();
  try {
    const draft = await api("/api/drafts", { method: "POST", body: { video_id: v.id, regenerate } });
    if (state.selected?.id !== v.id) return; // 그새 다른 영상을 골랐으면 무시
    state.draft = draft;
    renderDraft();
  } catch (e) {
    if (state.selected?.id !== v.id) return;
    $("draft-error").hidden = false;
    $("draft-error").textContent = e.message;
  } finally {
    if (state.selected?.id === v.id) {
      state.drafting = false;
      $("draft-loading").hidden = true;
      updatePostButton();
    }
  }
}

function renderDraft() {
  const v = state.selected, d = state.draft;
  $("d-video").href = v.url;
  $("d-thumb").src = v.thumbnail;
  $("d-title").textContent = v.title;
  $("d-meta").textContent = `${v.channel} · ${fmtDate(v.published_at)} · 유튜브에서 보기 ↗`;
  $("d-worry").textContent = d.worry;
  $("d-scenes").replaceChildren(...d.scenes.map((s) => el("li", {}, s)));
  $("d-persona").textContent = d.persona;
  const src = $("d-source");
  src.textContent = d.source === "자막" ? "자막 기반" : "자막 없음 · 제목·설명 기반";
  src.classList.toggle("weak", d.source !== "자막");
  $("d-comment").value = d.comment;
  $("draft").hidden = false;
  renderChecks(normalize(d.comment).length, d.problems);
}

function renderChecks(length, problems) {
  state.problems = problems;
  const r = state.status?.comment_rules || { min: 40, max: 120 };
  const count = $("d-count");
  count.textContent = `${length}자 / ${r.min}~${r.max}자`;
  count.classList.toggle("bad", length < r.min || length > r.max);
  const list = $("d-problems");
  list.classList.toggle("ok", problems.length === 0);
  list.replaceChildren(...(problems.length
    ? problems.map((p) => el("li", {}, p))
    : [el("li", {}, "규칙 통과 (글자 수 · 운명원 언급 · 링크/해시태그 없음 · 지어낸 후기 없음)")]));
  updatePostButton();
}

let checkTimer = null;
function onCommentInput() {
  const text = normalize($("d-comment").value);
  $("d-count").textContent = `${text.length}자`;
  clearTimeout(checkTimer);
  checkTimer = setTimeout(async () => {
    try {
      const res = await api("/api/check", { method: "POST", body: { text } });
      renderChecks(res.length, res.problems);
    } catch { /* 검사는 게시할 때 서버에서 다시 한다 */ }
  }, 250);
}

// ---------- ③ 댓글 달기 ----------
function postBlockReason() {
  const s = state.status, v = state.selected;
  if (state.job) return "게시 중이에요…";
  if (!v) return "① 목록에서 영상을 먼저 골라 주세요.";
  if (v.commented) return "이미 댓글을 단 영상이에요 (영상당 댓글 1개).";
  if (v.source === "rising") return "뜨기 직전 영상은 초안까지만 만들어요.";
  if (state.drafting) return "댓글 초안을 만드는 중이에요…";
  if (!state.draft) return "댓글 초안이 없어요.";
  if (state.problems.length) return "초안이 규칙에 맞지 않아요. ② 에서 고쳐 주세요.";
  if (s && s.today >= s.limit) return `오늘 게시 상한(${s.limit}개)에 도달했어요.`;
  if (s && !s.profiles.some((p) => p.ready)) return "로그인된 크롬 프로필이 없어요.";
  return "";
}

function updatePostButton() {
  const reason = postBlockReason();
  $("post").disabled = Boolean(reason);
  const profile = $("profile").value;
  $("post-reason").textContent = reason ||
    (profile === "auto" ? "가장 오래 쉰 계정으로 자동 배정돼요." : `${profile} 계정으로 게시돼요.`);
}

function renderSteps(job) {
  const steps = state.status?.steps || [];
  const idx = steps.findIndex((s) => s.code === job.step);
  const finished = job.state !== "running";
  $("steps").replaceChildren(...steps.map((s, i) => {
    let cls = "step", mark = String(i + 1);
    if (job.state === "success" || i < idx) { cls += " done"; mark = "✓"; }
    else if (i === idx && finished) { cls += " fail"; mark = "!"; }
    else if (i === idx) { cls += " active"; mark = ""; }
    const label = s.code === "typing" && i === idx && !finished ? `${s.label} ${job.progress || 0}%` : s.label;
    return el("li", { class: cls },
      el("span", { class: "dot" }, mark),
      el("span", {}, label),
      s.code === "typing" && i === idx && !finished
        ? el("span", { class: "bar" }, el("i", { style: `width:${job.progress || 0}%` }))
        : null,
    );
  }));
}

function renderResult(job) {
  const box = $("result");
  box.hidden = false;
  const shot = job.screenshot
    ? el("a", { href: job.screenshot, target: "_blank", rel: "noopener" }, el("img", { src: job.screenshot, alt: "게시 화면 캡처" }))
    : null;
  // replaceChildren 에 null 을 넘기면 "null" 글자가 찍히므로 빼고 넘긴다.
  const fill = (...nodes) => box.replaceChildren(...nodes.filter(Boolean));
  if (job.state === "success") {
    box.className = "result ok";
    fill(
      el("strong", {}, `게시 완료 · ${job.profile}`),
      el("a", { href: job.comment_url, target: "_blank", rel: "noopener" }, "댓글 보기 ↗"),
      shot,
    );
  } else if (job.state === "unverified") {
    box.className = "result warn";
    fill(
      el("strong", {}, "게시는 됐을 수 있어요"),
      el("span", {}, job.message),
      el("span", {}, "중복을 막기 위해 이 영상에는 다시 게시할 수 없어요. 유튜브에서 직접 확인해 주세요."),
      shot,
    );
  } else {
    box.className = "result bad";
    fill(el("strong", {}, "게시 실패"), el("span", {}, job.message), shot);
  }
}

async function startPost() {
  const v = state.selected;
  const text = normalize($("d-comment").value);
  $("result").hidden = true;
  try {
    const { job_id } = await api("/api/post", {
      method: "POST",
      body: { video_id: v.id, text, profile: $("profile").value },
    });
    state.job = { id: job_id, state: "running", step: "opening_profile", progress: 0 };
    updatePostButton();
    renderSteps(state.job);
    pollJob(job_id, v);
  } catch (e) {
    const box = $("result");
    box.hidden = false;
    box.className = "result bad";
    box.replaceChildren(el("strong", {}, e.message), ...(e.problems || []).map((p) => el("span", {}, `· ${p}`)));
    loadStatus();
  }
}

async function pollJob(jobId, video) {
  try {
    const job = await api(`/api/jobs/${jobId}`);
    renderSteps(job);
    if (job.state === "running") {
      setTimeout(() => pollJob(jobId, video), 600);
      return;
    }
    state.job = null;
    if (job.state === "success" || job.state === "unverified") {
      video.commented = true;
      state.videos.forEach((x) => { if (x.id === video.id) x.commented = true; });
      renderList();
    }
    renderResult(job);
    await Promise.all([loadStatus(), loadLog()]);
  } catch (e) {
    setTimeout(() => pollJob(jobId, video), 1500);
  }
}

// ---------- 기록 ----------
const STATUS_LABEL = { success: "성공", unverified: "확인 안 됨", failed: "실패", posting: "게시 중" };

async function loadLog() {
  const { rows } = await api("/api/log");
  const body = $("log-body");
  if (!rows.length) {
    body.replaceChildren(el("tr", { class: "empty-row" }, el("td", { colspan: 5 }, "아직 게시한 댓글이 없어요.")));
    return;
  }
  body.replaceChildren(...rows.map((r) =>
    el("tr", {},
      el("td", { class: "time" }, fmtTime(r.created_at)),
      el("td", { class: "title" },
        el("a", { href: `https://www.youtube.com/watch?v=${r.video_id}`, target: "_blank", rel: "noopener" }, r.video_title || r.video_id)),
      el("td", {}, r.profile),
      el("td", { class: "text" }, r.text),
      el("td", {},
        el("span", { class: `st ${r.status}` }, STATUS_LABEL[r.status] || r.status),
        el("span", { class: "st-sub" },
          r.comment_url ? el("a", { href: r.comment_url, target: "_blank", rel: "noopener" }, "댓글 보기") : null,
          r.screenshot ? el("a", { href: r.screenshot, target: "_blank", rel: "noopener" }, "캡처") : null,
          r.error ? el("span", {}, r.error) : null,
        ),
      ),
    ),
  ));
}

// ---------- 시작 ----------
document.querySelectorAll(".tab").forEach((t) => t.addEventListener("click", () => setTab(t.dataset.tab)));
$("load").addEventListener("click", loadVideos);
document.querySelectorAll("#sort button").forEach((b) => b.addEventListener("click", () => setSort(b.dataset.sort)));
$("url-form").addEventListener("submit", openUrl);
$("d-comment").addEventListener("input", onCommentInput);
$("regen").addEventListener("click", () => state.selected && selectVideo(state.selected, true));
$("profile").addEventListener("change", updatePostButton);
$("post").addEventListener("click", startPost);

loadStatus();
loadLog();
