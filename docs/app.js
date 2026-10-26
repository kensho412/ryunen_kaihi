"use strict";

const LS_PASS = "sfcw.pass";
const LS_FAV = "sfcw.fav";
const LS_SEEN = "sfcw.seenDays";
const DAYS = ["月曜日", "火曜日", "水曜日", "木曜日", "金曜日", "土曜日"];

const $ = (s, el = document) => el.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const store = {
  get(k, d) { try { const v = localStorage.getItem(k); return v == null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch {} },
  del(k) { try { localStorage.removeItem(k); } catch {} },
};

let data = null;
const ui = { openFilter: "all", ttDay: null };

// ---- 復号（scraper/run.py と同じ PBKDF2-SHA256 + AES-GCM） ----
const b64 = (s) => Uint8Array.from(atob(s), (c) => c.charCodeAt(0));
async function decrypt(env, pass) {
  const base = await crypto.subtle.importKey("raw", new TextEncoder().encode(pass), "PBKDF2", false, ["deriveKey"]);
  const key = await crypto.subtle.deriveKey(
    { name: "PBKDF2", hash: "SHA-256", salt: b64(env.salt), iterations: env.iter },
    base, { name: "AES-GCM", length: 256 }, false, ["decrypt"]);
  const pt = await crypto.subtle.decrypt({ name: "AES-GCM", iv: b64(env.iv) }, key, b64(env.ct));
  return JSON.parse(new TextDecoder().decode(pt));
}

async function load(pass) {
  const r = await fetch("data.enc.json?t=" + Date.now(), { cache: "no-store" });
  if (!r.ok) throw new Error("データがまだありません（Actions を一度実行してください）");
  return decrypt(await r.json(), pass);
}

// ---- 起動 ----
async function boot() {
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").catch(() => {});
  const saved = store.get(LS_PASS, null);
  if (saved) {
    try { data = await load(saved); return show(); } catch (e) { if (e.name !== "OperationError") return showLock(e.message); }
  }
  showLock();
}

function showLock(msg) {
  $("#lock").hidden = false;
  $("#app").hidden = true;
  if (msg) { $("#lock-err").textContent = msg; $("#lock-err").hidden = false; }
  $("#pass").focus();
}

$("#lock-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const pass = $("#pass").value;
  try {
    data = await load(pass);
    if ($("#remember").checked) store.set(LS_PASS, pass);
    show();
  } catch (err) {
    $("#lock-err").textContent = err.name === "OperationError" ? "パスフレーズが違います" : err.message;
    $("#lock-err").hidden = false;
  }
});

function show() {
  $("#lock").hidden = true;
  $("#app").hidden = false;
  $("#updated").textContent = "更新: " + new Date(data.updated).toLocaleString("ja-JP", { month: "numeric", day: "numeric", weekday: "short", hour: "2-digit", minute: "2-digit" });
  const b = $("#banner");
  b.hidden = !data.error;
  b.textContent = data.error ? "ログイン取得エラー: " + data.error + "（予約状況は前回のもの）" : "";
  renderMine(); renderOpen(); renderTT(); renderSet();
}

document.querySelectorAll(".tabbar button").forEach((btn) => btn.addEventListener("click", () => {
  document.querySelectorAll(".tabbar button").forEach((b) => b.classList.toggle("on", b === btn));
  document.querySelectorAll(".tab").forEach((t) => (t.hidden = t.id !== "tab-" + btn.dataset.tab));
  window.scrollTo(0, 0);
}));

// ---- 予約状況 ----
function renderMine() {
  const el = $("#tab-mine");
  const m = data.mine;
  if (m == null) {
    el.innerHTML = `<div class="empty"><b>ログイン情報が未設定です</b>GitHub Secrets に <code>WELLNESS_USER</code> と <code>WELLNESS_PASS</code> を設定すると、自分の予約状況がここに出ます。</div>`;
    return;
  }
  const today = new Date().toLocaleDateString("sv-SE");
  const res = m.reservations.filter((r) => !r.iso || r.iso >= today);
  // 取得中の体育(出欠に「予」がある行、無ければ最後の出欠行)で 15回までの進捗を出す
  const att = m.credits.filter(([k]) => k.endsWith("出欠"));
  const cur = att.find(([, v]) => /予\d/.test(v)) || att[att.length - 1];
  const num = (v, k) => +((v.match(new RegExp(k + "(\\d+)")) || [])[1] || 0);
  const progress = cur ? (() => {
    const [k, v] = cur, done = num(v, "出"), absent = num(v, "欠"), booked = num(v, "予");
    const pct = (x) => Math.min(100, (x / 15) * 100);
    return `<div class="card prog">
      <div class="row"><b>${esc(k.replace("出欠", ""))}</b><span class="muted small">出席 ${done} ・ 欠席 ${absent} ・ 予約 ${booked}</span></div>
      <div class="bar"><i class="done" style="width:${pct(done)}%"></i><i class="booked" style="width:${pct(booked)}%"></i></div>
      <div class="muted small">15回まで あと ${Math.max(0, 15 - done)} 回${booked ? `（予約分が全部出席なら あと ${Math.max(0, 15 - done - booked)} 回）` : ""}</div>
    </div>`;
  })() : "";
  const pill = (r) => r.cancelled ? `<span class="pill bad">${esc(r.cancelled)}</span>`
    : `<span class="pill ${r.status.includes("確定") ? "ok" : "few"}">${esc(r.status)}</span>`;
  el.innerHTML = `
    ${progress}
    <h2>予約中の授業（${res.length}）</h2>
    ${res.length ? res.map((r) => `
      <details class="card res">
        <summary>
          <div class="row">
            <div>
              <div class="s">${esc(r.date)} <span class="period">${esc(r.period)}</span></div>
              <div class="t">${esc(r.name)}</div>
              <div class="s">${esc(r.place)} ・ 強度${esc(r.intensity)}</div>
            </div>
            ${pill(r)}
          </div>
        </summary>
        <dl class="kv">
          <dt>教員</dt><dd>${esc(r.teacher)}</dd>
          <dt>形態</dt><dd>${esc(r.mode)}</dd>
          ${r.theme ? `<dt>テーマ</dt><dd>${esc(r.theme)}</dd>` : ""}
          ${r.content ? `<dt>内容</dt><dd class="pre">${esc(r.content)}</dd>` : ""}
        </dl>
      </details>`).join("") : `<div class="empty"><b>予約中の授業はありません</b>「空き」タブで受付中の授業を確認できます。</div>`}
    <p class="muted small">取消は当日9:00まで（1限は8:30まで）。抽選待ちは授業の13日前に抽選されます。</p>
    <h2>取得状況</h2>
    <div class="card"><dl class="kv">${m.credits.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join("")}</dl></div>
    ${m.priority.length ? `<h2>抽選優先度</h2><div class="card"><dl class="kv">${m.priority.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join("")}</dl></div>` : ""}`;
}

// ---- 空き授業 ----
function favs() { return store.get(LS_FAV, []); }
function toggleFav(name) {
  const f = new Set(favs());
  f.has(name) ? f.delete(name) : f.add(name);
  store.set(LS_FAV, [...f]);
  renderOpen(); renderTT();
}

function renderOpen() {
  const el = $("#tab-open");
  const slots = data.open.slots;
  const fav = new Set(favs());
  const dates = [...new Set(slots.map((s) => s.iso))];
  const seen = new Set(store.get(LS_SEEN, []));
  const newest = dates[dates.length - 1];
  const filters = [["all", "すべて"], ["fav", "★お気に入り"], ["new", "新規受付日"], ...dates.slice(0, 7).map((d) => [d, slots.find((s) => s.iso === d).date.replace(/^\d+月/, "")])];

  let list = slots;
  if (ui.openFilter === "fav") list = slots.filter((s) => fav.has(s.name));
  else if (ui.openFilter === "new") list = slots.filter((s) => s.iso === newest);
  else if (ui.openFilter !== "all") list = slots.filter((s) => s.iso === ui.openFilter);

  const byDay = {};
  list.forEach((s) => (byDay[s.iso] ||= []).push(s));

  el.innerHTML = `
    <p class="muted small">${esc(data.open.range)} ／ 毎朝6:00に14日後の分が受付開始、翌朝6:00に抽選</p>
    <div class="chips">${filters.map(([k, l]) => `<button class="chip ${ui.openFilter === k ? "on" : ""}" data-f="${esc(k)}">${esc(l)}</button>`).join("")}</div>
    ${Object.keys(byDay).length ? "" : `<div class="empty"><b>該当する空き授業はありません</b>${ui.openFilter === "fav" ? "時間割タブの☆でお気に入りを登録できます。" : ""}</div>`}
    ${Object.entries(byDay).map(([iso, items]) => `
      <h2 class="day ${iso === newest && !seen.has(iso) ? "new" : ""}">${esc(items[0].date)}</h2>
      ${items.map((s) => `
        <div class="card row">
          <div>
            <div class="t"><span class="period">${esc(s.period)}</span>${esc(s.name)}</div>
            <div class="s">${esc(s.teacher)} ・ ${esc(s.place)} ・ 強度${esc(s.intensity)}</div>
          </div>
          <div class="row">
            <span class="pill ${s.vacancy <= 3 ? "few" : "ok"}">空 ${esc(s.vacancy)}</span>
            <button class="star ${fav.has(s.name) ? "on" : ""}" data-fav="${esc(s.name)}" aria-label="お気に入り">${fav.has(s.name) ? "★" : "☆"}</button>
          </div>
        </div>`).join("")}
    `).join("")}`;
  el.querySelectorAll("[data-f]").forEach((b) => b.addEventListener("click", () => { ui.openFilter = b.dataset.f; renderOpen(); }));
  el.querySelectorAll("[data-fav]").forEach((b) => b.addEventListener("click", () => toggleFav(b.dataset.fav)));
  if (newest) store.set(LS_SEEN, [...seen, newest].slice(-30));
}

// ---- 時間割 ----
function renderTT() {
  const el = $("#tab-tt");
  const tt = data.timetable;
  const days = DAYS.filter((d) => tt.regular.some((c) => c.day === d));
  if (!ui.ttDay) ui.ttDay = days[(new Date().getDay() + 6) % 7] ? DAYS[(new Date().getDay() + 6) % 7] : days[0];
  if (!days.includes(ui.ttDay)) ui.ttDay = days[0];
  const fav = new Set(favs());
  const items = tt.regular.filter((c) => c.day === ui.ttDay);
  const periods = [...new Set(items.map((c) => c.period))];
  const tag = { 向: "制限者向き", 座: "座学", 限: "制限者限定" };
  const card = (c) => `
    <div class="card row">
      <div>
        <div class="t">${esc(c.name)} ${c.tags.map((t) => `<span class="pill tag">${tag[t]}</span>`).join(" ")}</div>
        <div class="s">${esc(c.teacher)}${c.lang ? " ・ " + esc(c.lang) : ""}</div>
      </div>
      <button class="star ${fav.has(c.name) ? "on" : ""}" data-fav="${esc(c.name)}" aria-label="お気に入り">${fav.has(c.name) ? "★" : "☆"}</button>
    </div>`;
  el.innerHTML = `
    <p class="muted small">${esc(tt.title)}</p>
    <div class="chips">${days.map((d) => `<button class="chip ${d === ui.ttDay ? "on" : ""}" data-d="${d}">${d.replace("曜日", "")}</button>`).join("")}</div>
    ${periods.map((p) => `<div class="tt-period"><b>${esc(p)}</b><div>${items.filter((c) => c.period === p).map(card).join("")}</div></div>`).join("")}
    ${tt.spot.length ? `<h2>スポット授業</h2>${tt.spot.map(card).join("")}` : ""}`;
  el.querySelectorAll("[data-d]").forEach((b) => b.addEventListener("click", () => { ui.ttDay = b.dataset.d; renderTT(); }));
  el.querySelectorAll("[data-fav]").forEach((b) => b.addEventListener("click", () => toggleFav(b.dataset.fav)));
}

// ---- 通知設定 ----
function renderSet() {
  const el = $("#tab-set");
  const n = data.ntfy || {};
  const sub = n.topic ? `${n.server.replace(/\/$/, "")}/${n.topic}` : null;
  el.innerHTML = `
    <h2>スマホ通知（ntfy）</h2>
    <div class="card" style="counter-reset:s">
      ${sub ? `
        <p class="step">App Store / Google Play で <b>ntfy</b> をインストール</p>
        <p class="step">「+」→ トピック名に次を入力して購読<br><code>${esc(n.topic)}</code></p>
        <p class="step">毎朝6時過ぎ、新しい日の受付開始を通知します</p>
        <p class="muted small">ブラウザで開く: <a href="${esc(sub)}" target="_blank" rel="noopener">${esc(sub)}</a></p>
      ` : `<p>GitHub Secrets に <code>NTFY_TOPIC</code> を設定すると通知が有効になります。</p>`}
    </div>
    <h2>通知の種類</h2>
    <div class="card">
      <p>🗓 <b>受付開始</b> — 14日後の授業が予約可能になった日（毎朝）</p>
      <p>⭐ <b>お気に入りに空き</b> — <code>FAVORITES</code> の種目に新しく空きが出たとき${n.favorites?.length ? `<br><span class="muted small">現在: ${esc(n.favorites.join("、"))}</span>` : ""}</p>
      <p>🎉 <b>抽選当選</b> ／ ⚠️ <b>抽選待ちが消えた</b> ／ ⛔ <b>休講</b> — 自分の予約に変化があったとき</p>
    </div>
    <p class="muted small">この画面の★はこの端末の表示用です。通知に使う種目は GitHub の Actions Variables <code>FAVORITES</code> で設定します。予約は必ず公式サイトで手動で行ってください。</p>
    <button class="sec-btn" id="logout">この端末のパスフレーズを消去</button>`;
  $("#logout").addEventListener("click", () => { store.del(LS_PASS); location.reload(); });
}

boot();
