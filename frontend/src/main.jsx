import { useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

const API = import.meta.env.VITE_API_URL || "http://localhost:8000";
const ADMIN_TOKEN = () => localStorage.getItem("uranus_admin_token") || "";

async function request(path, options = {}) {
  const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
  const token = ADMIN_TOKEN();
  if (token) headers["X-Admin-Token"] = token;
  const response = await fetch(`${API}${path}`, { ...options, headers });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail || body.error || `HTTP ${response.status}`);
  return body;
}

const shortJson = (value) => JSON.stringify(value, null, 2);
const time = (value) => value ? new Date(value).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "";

function App() {
  const [view, setView] = useState("chat");
  const [conversations, setConversations] = useState([]);
  const [conversationId, setConversationId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [providers, setProviders] = useState([]);
  const [models, setModels] = useState([]);
  const [selectedModel, setSelectedModel] = useState("");
  const [prompt, setPrompt] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [draft, setDraft] = useState("");
  const [runId, setRunId] = useState(null);
  const [runEvents, setRunEvents] = useState([]);
  const [approvals, setApprovals] = useState([]);
  const [settings, setSettings] = useState({});
  const [skills, setSkills] = useState([]);
  const [terminalCommand, setTerminalCommand] = useState("pwd && ls -la");
  const [terminalOutput, setTerminalOutput] = useState(null);
  const [browserUrl, setBrowserUrl] = useState("https://example.com");
  const [browserSnapshot, setBrowserSnapshot] = useState(null);
  const [workspace, setWorkspace] = useState([]);
  const [selectedFile, setSelectedFile] = useState(null);
  const [fileContent, setFileContent] = useState("");
  const [notice, setNotice] = useState("");
  const eventSource = useRef(null);

  const activeProvider = useMemo(() => selectedModel.split(":")[0] || "", [selectedModel]);

  useEffect(() => {
    loadBootstrap();
    loadConversations();
    loadWorkspace();
    return () => eventSource.current?.close();
  }, []);

  async function loadBootstrap() {
    try {
      const data = await request("/api/bootstrap");
      setProviders(data.providers || []);
      setSettings(data.settings || {});
      setSkills(data.skills || []);
      const configured = (data.providers || []).find((item) => item.key_configured);
      const first = configured || (data.providers || []).find((item) => item.id === "opencode") || (data.providers || []).find((item) => item.id === "ollama");
      if (first) loadModels(first.id);
    } catch (error) { showNotice(error.message); }
  }

  async function loadConversations() {
    try { setConversations(await request("/api/conversations")); } catch (error) { showNotice(error.message); }
  }

  async function loadConversation(id) {
    try {
      const data = await request(`/api/conversations/${id}`);
      setConversationId(id);
      setMessages(data.messages || []);
      setDraft("");
      setRunEvents([]);
      setView("chat");
    } catch (error) { showNotice(error.message); }
  }

  async function loadModels(providerId) {
    try {
      const items = await request(`/api/providers/${providerId}/models`);
      setModels(items || []);
      if (items?.[0]) setSelectedModel(`${providerId}:${items[0].id}`);
      showNotice(`${items?.length || 0} моделей загружено`);
    } catch (error) { showNotice(error.message); }
  }

  async function loadWorkspace() {
    try {
      const data = await request("/api/workspace/list?path=.");
      setWorkspace(data.files || []);
    } catch (error) { showNotice(error.message); }
  }

  function showNotice(message) {
    setNotice(message);
    window.setTimeout(() => setNotice(""), 3600);
  }

  function newTask() {
    eventSource.current?.close();
    setConversationId(null);
    setMessages([]);
    setRunEvents([]);
    setApprovals([]);
    setDraft("");
    setStreaming(false);
    setView("chat");
  }

  async function sendPrompt(event) {
    event?.preventDefault();
    if (!prompt.trim() || streaming) return;
    if (!selectedModel) {
      showNotice("Сначала выбери модель в верхней панели или настрой провайдера в админке.");
      setView("admin");
      return;
    }
    const text = prompt.trim();
    setPrompt("");
    setMessages((items) => [...items, { role: "user", content: text, created_at: new Date().toISOString() }]);
    setStreaming(true);
    setDraft("");
    setRunEvents([]);
    setApprovals([]);
    try {
      const run = await request("/api/runs", { method: "POST", body: JSON.stringify({ model: selectedModel, prompt: text, conversation_id: conversationId }) });
      setRunId(run.run_id);
      setConversationId(run.conversation_id);
      const source = new EventSource(`${API}/api/runs/${run.run_id}/events`);
      eventSource.current = source;
      source.addEventListener("text", (message) => {
        const data = JSON.parse(message.data);
        setDraft((value) => value + (data.content || ""));
      });
      source.addEventListener("step", (message) => setRunEvents((items) => [...items, { kind: "step", data: JSON.parse(message.data) }]));
      source.addEventListener("tool_start", (message) => setRunEvents((items) => [...items, { kind: "tool", data: JSON.parse(message.data), status: "running" }]));
      source.addEventListener("tool_result", (message) => setRunEvents((items) => [...items, { kind: "tool", data: JSON.parse(message.data), status: "done" }]));
      source.addEventListener("approval_required", (message) => {
        const data = JSON.parse(message.data);
        setApprovals((items) => [...items, data]);
        setRunEvents((items) => [...items, { kind: "approval", data }]);
      });
      source.addEventListener("final", (message) => {
        const data = JSON.parse(message.data);
        setDraft("");
        if (data.content) setMessages((items) => [...items, { role: "assistant", content: data.content, created_at: new Date().toISOString() }]);
      });
      source.addEventListener("error", (message) => {
        if (message.data) {
          const data = JSON.parse(message.data);
          showNotice(data.message || "Ошибка запуска");
        }
      });
      source.addEventListener("done", () => {
        source.close();
        setStreaming(false);
        loadConversations();
      });
    } catch (error) {
      setStreaming(false);
      showNotice(error.message);
    }
  }

  async function decideApproval(approvalId, decision) {
    try {
      await request(`/api/approvals/${approvalId}`, { method: "POST", body: JSON.stringify({ decision }) });
      setApprovals((items) => items.filter((item) => item.approval_id !== approvalId));
      showNotice(decision === "approved" ? "Действие разрешено" : "Действие отклонено");
    } catch (error) { showNotice(error.message); }
  }

  async function stopRun() {
    if (!runId) return;
    try { await request(`/api/runs/${runId}/stop`, { method: "POST" }); } catch (error) { showNotice(error.message); }
  }

  async function runTerminal(event) {
    event?.preventDefault();
    if (!terminalCommand.trim()) return;
    setTerminalOutput({ stdout: "", stderr: "Выполняется…" });
    try {
      const data = await request("/api/terminal/exec", { method: "POST", body: JSON.stringify({ command: terminalCommand, timeout: 60 }) });
      setTerminalOutput(data);
      loadWorkspace();
    } catch (error) { setTerminalOutput({ stderr: error.message }); }
  }

  async function browserAction(action, extra = {}) {
    try {
      const data = await request("/api/browser/action", { method: "POST", body: JSON.stringify({ action, ...extra }) });
      setBrowserSnapshot(data);
      if (data.path) showNotice(`Screenshot сохранён: ${data.path}`);
    } catch (error) { showNotice(error.message); }
  }

  async function readFile(path) {
    try {
      const data = await request(`/api/workspace/read?path=${encodeURIComponent(path)}`);
      setSelectedFile(path);
      setFileContent(data.content || data.error || "");
    } catch (error) { showNotice(error.message); }
  }

  async function saveSetting(key, value) {
    try {
      await request(`/api/settings/${key}`, { method: "PUT", body: JSON.stringify({ value: String(value) }) });
      setSettings((items) => ({ ...items, [key]: String(value) }));
      showNotice("Настройка сохранена");
    } catch (error) { showNotice(error.message); }
  }

  async function saveProvider(provider) {
    try {
      const key = document.querySelector(`[data-provider-key="${provider.id}"]`)?.value?.trim();
      const base = document.querySelector(`[data-provider-base="${provider.id}"]`)?.value;
      const proxy = document.querySelector(`[data-provider-proxy="${provider.id}"]`)?.value?.trim();
      const payload = { base_url: base, enabled: provider.enabled };
      if (proxy) payload.proxy_url = proxy;
      if (key) payload.api_key = key;
      await request(`/api/providers/${provider.id}`, { method: "PUT", body: JSON.stringify(payload) });
      setProviders(await request("/api/providers"));
      showNotice(`${provider.name} сохранён`);
    } catch (error) { showNotice(error.message); }
  }

  async function clearProviderProxy(provider) {
    try {
      await request(`/api/providers/${provider.id}`, { method: "PUT", body: JSON.stringify({ proxy_url: null }) });
      setProviders(await request("/api/providers"));
      showNotice(`Proxy для ${provider.name} отключён`);
    } catch (error) { showNotice(error.message); }
  }

  async function testProvider(provider) {
    const model = document.querySelector(`[data-provider-model="${provider.id}"]`)?.value || "";
    try {
      const data = await request(`/api/providers/${provider.id}/test${model ? `?model=${encodeURIComponent(model)}` : ""}`, { method: "POST" });
      showNotice(`${provider.name}: ${data.text || "OK"}`);
    } catch (error) { showNotice(error.message); }
  }

  async function toggleSkill(skill) {
    try {
      await request(`/api/skills/${skill.slug}`, { method: "PUT", body: JSON.stringify({ ...skill, enabled: !Boolean(skill.enabled) }) });
      setSkills(await request("/api/skills"));
    } catch (error) { showNotice(error.message); }
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand"><span className="brand-mark">U</span><span>Uranus<span className="brand-accent">-AI</span></span><span className="version">0.1</span></div>
        <button className="new-task" onClick={newTask}><span>＋</span> Новая задача</button>
        <nav className="main-nav">
          <button className={view === "chat" ? "nav-item active" : "nav-item"} onClick={() => setView("chat")}><span>◈</span> Агент</button>
          <button className={view === "computer" ? "nav-item active" : "nav-item"} onClick={() => setView("computer")}><span>▣</span> Computer</button>
          <button className={view === "admin" ? "nav-item active" : "nav-item"} onClick={() => setView("admin")}><span>⚙</span> Настройки</button>
        </nav>
        <div className="sidebar-label">ИСТОРИЯ</div>
        <div className="conversation-list">
          {conversations.map((item) => <button key={item.id} className={conversationId === item.id ? "conversation active" : "conversation"} onClick={() => loadConversation(item.id)}><span className="conversation-dot" />{item.title || "Новый запуск"}<small>{time(item.updated_at)}</small></button>)}
          {!conversations.length && <div className="empty-side">Здесь появятся твои запуски.</div>}
        </div>
        <div className="sidebar-bottom"><div className="status-dot" /> локальный режим <span className="lock">⌁</span></div>
      </aside>

      <main className="main-panel">
        <header className="topbar">
          <div className="breadcrumb"><span>Uranus-AI</span><span className="slash">/</span><strong>{view === "chat" ? "Агент" : view === "computer" ? "Computer" : "Настройки"}</strong></div>
          <div className="top-actions">
            <label className="model-picker"><span className="live-dot" />
              <select value={selectedModel} onChange={(event) => setSelectedModel(event.target.value)}>
                <option value="">Модель не выбрана</option>
                {models.map((item) => <option key={`${item.provider}:${item.id}`} value={`${item.provider}:${item.id}`}>{item.name || item.id}</option>)}
              </select>
            </label>
            {activeProvider && <button className="icon-button" title="Обновить модели" onClick={() => loadModels(activeProvider)}>↻</button>}
            {streaming && <button className="stop-button" onClick={stopRun}>Остановить</button>}
            <button className="avatar" onClick={() => setView("admin")}>G</button>
          </div>
        </header>

        {view === "chat" && <ChatView messages={messages} draft={draft} prompt={prompt} setPrompt={setPrompt} sendPrompt={sendPrompt} streaming={streaming} runEvents={runEvents} approvals={approvals} decideApproval={decideApproval} />}
        {view === "computer" && <ComputerView terminalCommand={terminalCommand} setTerminalCommand={setTerminalCommand} runTerminal={runTerminal} terminalOutput={terminalOutput} browserUrl={browserUrl} setBrowserUrl={setBrowserUrl} browserSnapshot={browserSnapshot} browserAction={browserAction} workspace={workspace} readFile={readFile} selectedFile={selectedFile} fileContent={fileContent} />}
        {view === "admin" && <AdminView providers={providers} saveProvider={saveProvider} clearProviderProxy={clearProviderProxy} testProvider={testProvider} loadModels={loadModels} settings={settings} saveSetting={saveSetting} skills={skills} toggleSkill={toggleSkill} />}
      </main>
      {notice && <div className="toast">{notice}</div>}
    </div>
  );
}

function ChatView({ messages, draft, prompt, setPrompt, sendPrompt, streaming, runEvents, approvals, decideApproval }) {
  const suggestions = ["Проверь структуру проекта и предложи улучшения", "Найди в интернете актуальные решения для задачи", "Сделай диагностику и запусти тесты", "Открой сайт и выпиши ключевые факты"];
  return <section className="chat-view">
    <div className="chat-scroll">
      {!messages.length && !draft && <div className="welcome"><div className="orbit"><span>U</span></div><p className="eyebrow">AGENT WORKSPACE</p><h1>Что будем делать?</h1><p className="welcome-sub">Опиши результат. Uranus-AI составит план, использует инструменты и покажет доказательства выполнения.</p><div className="suggestions">{suggestions.map((item) => <button key={item} onClick={() => setPrompt(item)}>{item}<span>↗</span></button>)}</div></div>}
      <div className="message-stack">{messages.map((message, index) => <Message key={`${message.created_at}-${index}`} message={message} />)}{draft && <Message message={{ role: "assistant", content: draft }} live />}</div>
      {(runEvents.length > 0 || approvals.length > 0) && <ActivityPanel events={runEvents} approvals={approvals} decideApproval={decideApproval} />}
    </div>
    <form className="composer-wrap" onSubmit={sendPrompt}>
      <div className="composer">
        <textarea value={prompt} onChange={(event) => setPrompt(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); sendPrompt(event); } }} placeholder="Поставь задачу Uranus-AI…" rows="1" />
        <div className="composer-footer"><span className="composer-hint">Shift + Enter — новая строка</span><button className="send-button" disabled={streaming || !prompt.trim()}>{streaming ? "…" : "↑"}</button></div>
      </div>
      <p className="composer-note">Агент работает только внутри Docker workspace. Опасные действия запрашивают подтверждение.</p>
    </form>
  </section>;
}

function Message({ message, live }) {
  const isUser = message.role === "user";
  return <article className={isUser ? "message user-message" : "message assistant-message"}><div className="message-label">{isUser ? "ТЫ" : <><span className="tiny-mark">U</span> URANUS-AI</>}{live && <span className="typing">печатает</span>}</div><div className="message-content">{message.content}</div></article>;
}

function ActivityPanel({ events, approvals, decideApproval }) {
  return <div className="activity-panel"><div className="activity-heading"><span className="pulse" /> Журнал выполнения <span className="activity-count">{events.length}</span></div>{events.map((event, index) => <div className="activity-row" key={`${event.kind}-${index}`}><span className={event.kind === "approval" ? "activity-icon warning" : "activity-icon"}>{event.kind === "tool" ? "⌘" : event.kind === "step" ? "◌" : "!"}</span><div><strong>{event.kind === "tool" ? event.data.tool_name : event.kind === "step" ? `Шаг ${event.data.step} из ${event.data.max_steps}` : `Подтверждение: ${event.data.tool_name}`}</strong><small>{event.kind === "tool" ? (event.status === "done" ? "завершено" : "выполняется…") : event.kind === "approval" ? "ожидает решения" : "агент строит контекст"}</small></div></div>)}{approvals.map((approval) => <div className="approval-card" key={approval.approval_id}><div><strong>Разрешить {approval.tool_name}?</strong><pre>{shortJson(approval.arguments)}</pre></div><div className="approval-actions"><button onClick={() => decideApproval(approval.approval_id, "denied")}>Отклонить</button><button className="approve" onClick={() => decideApproval(approval.approval_id, "approved")}>Разрешить</button></div></div>)}</div>;
}

function ComputerView(props) {
  const { terminalCommand, setTerminalCommand, runTerminal, terminalOutput, browserUrl, setBrowserUrl, browserSnapshot, browserAction, workspace, readFile, selectedFile, fileContent } = props;
  return <section className="computer-view"><div className="section-heading"><div><p className="eyebrow">MANUS-LIKE COMPUTER</p><h1>Рабочая среда</h1><p>Изолированный браузер, терминал и workspace в одном окне.</p></div><span className="security-badge">● sandboxed</span></div><div className="computer-grid"><div className="panel browser-panel"><div className="panel-title"><span className="panel-icon cyan">◎</span><div><strong>Browser</strong><small>Playwright · отдельный профиль</small></div><button className="small-button" onClick={() => browserAction("snapshot")}>Snapshot</button></div><form className="browser-bar" onSubmit={(event) => { event.preventDefault(); browserAction("open", { url: browserUrl }); }}><input value={browserUrl} onChange={(event) => setBrowserUrl(event.target.value)} /><button>Открыть</button></form><div className="browser-actions"><button onClick={() => browserAction("open", { url: browserUrl })}>↗ Open</button><button onClick={() => browserAction("scroll", { pixels: 700 })}>↓ Scroll</button><button onClick={() => browserAction("screenshot", { path: "artifacts/browser.png" })}>▧ Screenshot</button></div><div className="browser-output">{browserSnapshot ? <><div className="snapshot-meta"><strong>{browserSnapshot.title || "Без заголовка"}</strong><span>{browserSnapshot.url}</span></div><pre>{browserSnapshot.text || browserSnapshot.error || ""}</pre></> : <div className="empty-state">Открой публичный URL. Для авторизованных сайтов используй отдельный профиль браузера и не вводи секреты в общий чат.</div>}</div></div><div className="panel terminal-panel"><div className="panel-title"><span className="panel-icon purple">⌁</span><div><strong>Terminal</strong><small>bash · /workspace · non-root</small></div><span className="terminal-status">ready</span></div><form onSubmit={runTerminal}><textarea value={terminalCommand} onChange={(event) => setTerminalCommand(event.target.value)} /><button className="terminal-run">▶ Выполнить команду</button></form><div className="terminal-output">{terminalOutput ? <><div className="terminal-prompt">uranus@sandbox:/workspace$</div><pre className={terminalOutput.ok ? "success-text" : "error-text"}>{terminalOutput.stdout || terminalOutput.stderr || ""}</pre></> : <div className="empty-state">Команды выполняются в отдельном контейнере с таймаутом и ограниченным workspace.</div>}</div></div></div><div className="workspace-panel panel"><div className="panel-title"><span className="panel-icon amber">⌂</span><div><strong>Workspace</strong><small>{workspace.length} объектов</small></div><button className="small-button" onClick={() => window.location.reload()}>Обновить</button></div><div className="workspace-body"><div className="file-list">{workspace.map((file) => <button key={file.path} className={selectedFile === file.path ? "file-row selected" : "file-row"} onClick={() => file.type === "file" && readFile(file.path)}><span>{file.type === "dir" ? "▸" : "·"}</span>{file.path}<small>{file.size ? `${file.size} B` : "dir"}</small></button>)}{!workspace.length && <div className="empty-state">Workspace пуст. Попроси агента создать файл.</div>}</div><div className="file-preview">{selectedFile ? <><div className="preview-title">{selectedFile}</div><pre>{fileContent}</pre></> : <div className="empty-state">Выбери текстовый файл, чтобы посмотреть его содержимое.</div>}</div></div></div></section>;
}

function AdminView({ providers, saveProvider, clearProviderProxy, testProvider, loadModels, settings, saveSetting, skills, toggleSkill }) {
  const settingRows = [["approval_mode", "Режим подтверждений", "ask"], ["max_steps", "Максимум шагов", "12"], ["max_tokens", "Токенов на ответ", "2048"], ["temperature", "Temperature", "0.2"], ["allow_browser", "Разрешить браузер", "true"], ["allow_web", "Разрешить веб", "true"]];
  return <section className="admin-view"><div className="section-heading"><div><p className="eyebrow">CONTROL PLANE</p><h1>Настройки Uranus-AI</h1><p>Ключи, модели, безопасность, skills и поведение агента — без редактирования файлов.</p></div><span className="security-badge">⌁ local-first</span></div><div className="admin-grid"><div className="panel providers-panel"><div className="panel-title"><span className="panel-icon cyan">◒</span><div><strong>Провайдеры моделей</strong><small>Ключи шифруются в SQLite</small></div></div><div className="provider-list">{providers.map((provider) => <div className="provider-card" key={provider.id}><div className="provider-head"><div className="provider-name"><span className={`provider-logo ${provider.id}`}>{provider.name.slice(0, 1)}</span><div><strong>{provider.name}</strong><small>{provider.kind} · {provider.key_configured ? "ключ настроен" : "ключ не задан"}</small></div></div><label className="switch"><input type="checkbox" checked={provider.enabled} onChange={(event) => saveProvider({ ...provider, enabled: event.target.checked })} /><span /></label></div><input className="admin-input" data-provider-key={provider.id} type="password" placeholder={provider.key_configured ? "Оставить текущий ключ" : "API key"} /><input className="admin-input" data-provider-base={provider.id} defaultValue={provider.base_url} placeholder="Base URL" /><input className="admin-input" data-provider-proxy={provider.id} defaultValue="" placeholder={provider.proxy_configured ? `Текущий: ${provider.proxy_hint || "настроен"}; введи новый, чтобы заменить` : "Proxy: socks5://127.0.0.1:9050 или http://127.0.0.1:10808"} /><div className="provider-actions"><input className="model-input" data-provider-model={provider.id} placeholder="Модель для теста" /><button onClick={() => loadModels(provider.id)}>Модели</button><button onClick={() => testProvider(provider)}>Проверить</button>{provider.proxy_configured && <button onClick={() => clearProviderProxy(provider)}>Сбросить proxy</button>}<button className="primary-small" onClick={() => saveProvider(provider)}>Сохранить</button></div></div>)}</div></div><div className="side-admin"><div className="panel settings-panel"><div className="panel-title"><span className="panel-icon purple">⚙</span><div><strong>Поведение агента</strong><small>изменения применяются сразу</small></div></div>{settingRows.map(([key, label, fallback]) => <SettingRow key={key} label={label} value={settings[key] ?? fallback} onSave={(value) => saveSetting(key, value)} />)}</div><div className="panel skills-panel"><div className="panel-title"><span className="panel-icon amber">✦</span><div><strong>Agent Skills</strong><small>progressive disclosure</small></div></div>{skills.map((skill) => <div className="skill-row" key={skill.slug}><div><strong>{skill.name}</strong><small>{skill.description}</small></div><button className={skill.enabled ? "skill-toggle enabled" : "skill-toggle"} onClick={() => toggleSkill(skill)}>{skill.enabled ? "ON" : "OFF"}</button></div>)}</div></div></div><div className="admin-footnote">Безопасный старт: оставь <code>approval_mode=ask</code>. Для OpenRouter/Groq используй только бесплатные модели во время проверки. Proxy настраивается отдельно для каждого провайдера; <code>127.0.0.1:10808</code> и <code>127.0.0.1:9050</code> в Docker идут через host gateway. Секреты не попадают в git и не отдаются frontend.</div></section>;
}

function SettingRow({ label, value, onSave }) {
  const [draft, setDraft] = useState(value);
  return <label className="setting-row"><span>{label}</span><div><input value={draft} onChange={(event) => setDraft(event.target.value)} onBlur={() => onSave(draft)} /><small>сохранить</small></div></label>;
}

createRoot(document.getElementById("root")).render(<App />);
export default App;
