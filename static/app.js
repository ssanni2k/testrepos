async function api(url, opts) {
  const res = await fetch(url, opts);
  const ct = res.headers.get("content-type") || "";
  if (!ct.includes("application/json")) {
    if (!res.ok) throw new Error("HTTP " + res.status);
    return { ok: true };
  }
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || "Ошибка");
  return data;
}

function log(msg, isError = false) {
  const el = document.getElementById("log");
  const line = document.createElement("div");
  line.className = "log-line" + (isError ? " log-error" : "");
  line.textContent = `[${new Date().toLocaleTimeString()}] ${msg}`;
  el.prepend(line);
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

document.querySelectorAll("nav a").forEach(a => {
  a.addEventListener("click", e => {
    e.preventDefault();
    document.querySelectorAll("nav a").forEach(x => x.classList.remove("active"));
    document.querySelectorAll(".panel").forEach(p => p.classList.add("hidden"));
    a.classList.add("active");
    document.getElementById("tab-" + a.dataset.tab).classList.remove("hidden");
  });
});

async function loadUser() {
  try {
    const u = await api("/api/user");
    document.getElementById("hero-title").textContent = u.name.toUpperCase();
    document.getElementById("hero-info").textContent =
      `${u.email} · ${u.account_type} · ${u.country}`;
  } catch (e) {
    document.getElementById("hero-title").textContent = "ОШИБКА";
    log(e.message, true);
  }
}

async function loadSpace() {
  try {
    const s = await api("/api/space");
    document.getElementById("space-fill").style.width = s.percent + "%";
    document.getElementById("space-label").textContent =
      `занято ${s.used_h} из ${s.allocated_h} (${s.percent}%) · свободно ${s.free_h}`;
  } catch (e) { log(e.message, true); }
}

function renderList(elId, items, tpl) {
  const el = document.getElementById(elId);
  if (!items.length) { el.innerHTML = "<li class='empty'>пусто</li>"; return; }
  el.innerHTML = items.map(tpl).join("");
}

async function loadFolder() {
  const path = document.getElementById("browse-path").value.trim();
  try {
    const data = await api("/api/list?path=" + encodeURIComponent(path));
    renderList("file-list", data.items, item => {
      const icon = item.type === "folder" ? "📁" : "📄";
      const dl = item.type === "file"
        ? `<a href="/api/download?path=${encodeURIComponent(item.path)}" title="Скачать">⬇</a>`
        : "";
      return `<li>
        <span class="icon">${icon}</span>
        <span class="name">${escapeHtml(item.name)}</span>
        <span class="meta">${item.size_h || ""}</span>
        <span class="actions">
          ${dl}
          <a href="#" title="Открыть" onclick="event.preventDefault();openPath('${escapeHtml(item.path).replace(/'/g,"\\'")}')">→</a>
        </span>
      </li>`;
    });
    log(`Открыто: ${data.path}`);
  } catch (e) { log(e.message, true); }
}

function openPath(p) {
  document.getElementById("browse-path").value = p;
  document.querySelector('nav a[data-tab="files"]').click();
  loadFolder();
}

async function createFolder() {
  const path = document.getElementById("create-path").value.trim();
  if (!path) return log("Укажите путь", true);
  try {
    const r = await api("/api/folder/create", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({path})
    });
    log(`Папка создана: ${r.path}`);
  } catch (e) { log(e.message, true); }
}

async function deleteEntry() {
  const path = document.getElementById("delete-path").value.trim();
  if (!path) return log("Укажите путь", true);
  if (!confirm(`Удалить ${path}?`)) return;
  try {
    const r = await api("/api/delete", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({path})
    });
    log(`Удалено: ${r.path}`);
  } catch (e) { log(e.message, true); }
}

async function moveEntry() {
  const src = document.getElementById("move-src").value.trim();
  const dst = document.getElementById("move-dst").value.trim();
  if (!src || !dst) return log("Заполните оба поля", true);
  try {
    const r = await api("/api/move", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({src, dst})
    });
    log(`Перемещено: ${r.src} → ${r.dst}`);
  } catch (e) { log(e.message, true); }
}

async function copyEntry() {
  const src = document.getElementById("move-src").value.trim();
  const dst = document.getElementById("move-dst").value.trim();
  if (!src || !dst) return log("Заполните оба поля", true);
  try {
    const r = await api("/api/copy", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({src, dst})
    });
    log(`Скопировано: ${r.src} → ${r.dst}`);
  } catch (e) { log(e.message, true); }
}

async function uploadFile() {
  const path = document.getElementById("upload-path").value.trim();
  const f = document.getElementById("upload-file").files[0];
  const overwrite = document.getElementById("upload-overwrite").checked;
  if (!path || !f) return log("Укажите путь и выберите файл", true);
  const fd = new FormData();
  fd.append("path", path);
  fd.append("file", f);
  fd.append("overwrite", overwrite);
  try {
    const r = await api("/api/upload", {method: "POST", body: fd});
    log(`Загружено: ${r.path} (${r.size_h})`);
  } catch (e) { log(e.message, true); }
}

async function showMeta() {
  const path = document.getElementById("meta-path").value.trim();
  if (!path) return log("Укажите путь", true);
  try {
    const m = await api("/api/metadata?path=" + encodeURIComponent(path));
    const parts = [`${m.path}`, m.type];
    if (m.size_h) parts.push(m.size_h);
    if (m.modified) parts.push(m.modified);
    if (m.id) parts.push("id=" + m.id);
    log("Метаданные: " + parts.join(" · "));
  } catch (e) { log(e.message, true); }
}

async function shareIt() {
  const path = document.getElementById("share-path").value.trim();
  if (!path) return log("Укажите путь", true);
  try {
    const r = await api("/api/share", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({path})
    });
    log(`Ссылка${r.existing ? " (уже была)" : ""}: ${r.url}`);
  } catch (e) { log(e.message, true); }
}

async function loadSharedLinks() {
  try {
    const data = await api("/api/shared-links");
    renderList("shared-list", data.items, item =>
      `<li>
        <span class="icon">${item.type === "folder" ? "📁" : "📄"}</span>
        <span class="name">${escapeHtml(item.name)}</span>
        <a href="${item.url}" target="_blank">открыть ↗</a>
      </li>`);
    log(`Расшаренных ресурсов: ${data.items.length}`);
  } catch (e) { log(e.message, true); }
}

async function doSearch() {
  const q = document.getElementById("search-q").value.trim();
  if (!q) return log("Введите запрос", true);
  const filenameOnly = document.getElementById("search-filename-only").checked;
  try {
    const data = await api(`/api/search?q=${encodeURIComponent(q)}&filename_only=${filenameOnly}`);
    renderList("search-list", data.items, item =>
      `<li>
        <span class="icon">${item.type === "folder" ? "📁" : "📄"}</span>
        <span class="name">${escapeHtml(item.path)}</span>
      </li>`);
    log(`Найдено: ${data.items.length}`);
  } catch (e) { log(e.message, true); }
}

loadUser();
loadSpace();
loadFolder();
