"""
generate_dashboard.py
Читает state/users.json, state/sent_signals.json, state/bot.log и генерирует
dashboard.html с 3 вкладками: Подписчики, Отправленные сигналы, Логи.

Запуск:
    python generate_dashboard.py
"""
from __future__ import annotations

import json
import webbrowser
from datetime import datetime, timezone
from pathlib import Path

STATE_DIR = Path("state")
USERS_PATH = STATE_DIR / "users.json"
SENT_PATH = STATE_DIR / "sent_signals.json"
LOG_PATH = STATE_DIR / "bot.log"
OUTPUT_HTML = Path("dashboard.html")

LOG_TAIL_LINES = 1000


def _read_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def _days_between(iso_str: str, now: datetime) -> str:
    if not iso_str:
        return "-"
    try:
        dt = datetime.fromisoformat(iso_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        delta = now - dt
        days = delta.total_seconds() / 86400
        return f"{days:.1f}"
    except ValueError:
        return "-"


def load_subscribers() -> list[dict]:
    data = _read_json(USERS_PATH, [])
    now = datetime.now(timezone.utc)
    out = []
    for u in data:
        if isinstance(u, int):
            u = {"id": u}
        row = {
            "id": u.get("id"),
            "username": u.get("username") or "",
            "first_name": u.get("first_name") or "",
            "joined_at": u.get("joined_at") or "",
            "last_active": u.get("last_active") or "",
            "days_subscribed": _days_between(u.get("joined_at", ""), now),
            "days_since_active": _days_between(u.get("last_active", ""), now),
        }
        out.append(row)
    return out


def load_sent_signals() -> list[dict]:
    raw = _read_json(SENT_PATH, {})
    out = []
    for key, payload in raw.items():
        meta = (payload or {}).get("meta") or {}
        out.append({
            "key": key,
            "strategy": payload.get("strategy", ""),
            "symbol": payload.get("symbol", ""),
            "source_tf": meta.get("source_tf", payload.get("timeframe", "")),
            "direction": payload.get("direction", ""),
            "ob1h_cur_time": meta.get("ob1h_cur_time", ""),
            "sent_at": payload.get("sent_at", ""),
            "price": payload.get("price", ""),
        })
    return out


def load_log_lines() -> list[dict]:
    if not LOG_PATH.exists():
        return []
    try:
        with LOG_PATH.open("r", encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return []
    tail = lines[-LOG_TAIL_LINES:]
    out = []
    for raw in tail:
        raw = raw.rstrip("\n")
        level = "INFO"
        ts = ""
        msg = raw
        try:
            # формат: "2026-04-23T21:30:45.123+00:00 [LEVEL] message"
            if raw and raw[0].isdigit():
                ts_end = raw.find(" ")
                if ts_end > 0:
                    ts = raw[:ts_end]
                    rest = raw[ts_end + 1:]
                    if rest.startswith("["):
                        lvl_end = rest.find("]")
                        if lvl_end > 0:
                            level = rest[1:lvl_end]
                            msg = rest[lvl_end + 1:].lstrip()
        except Exception:
            pass
        out.append({"ts": ts, "level": level.upper(), "msg": msg})
    return out


def build_html(subs: list[dict], signals: list[dict], logs: list[dict]) -> str:
    subs_json = json.dumps(subs, ensure_ascii=False, default=str)
    signals_json = json.dumps(signals, ensure_ascii=False, default=str)
    logs_json = json.dumps(logs, ensure_ascii=False, default=str)

    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<title>Bot Dashboard</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; padding: 20px;
    background: #0d1117; color: #c9d1d9;
    font-family: -apple-system, "SF Pro Text", "Segoe UI", sans-serif;
    font-size: 14px;
  }}
  h1 {{ color: #f0f6fc; margin: 0 0 16px 0; }}
  .summary {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
    gap: 12px; margin-bottom: 16px;
  }}
  .summary-card {{
    background: #161b22; border: 1px solid #30363d;
    border-radius: 8px; padding: 12px 16px;
  }}
  .summary-card h3 {{ margin: 0 0 6px 0; color: #58a6ff; font-size: 14px; }}
  .summary-card p {{ margin: 0; color: #8b949e; font-size: 12px; }}
  .tabs {{
    display: flex; gap: 4px;
    border-bottom: 1px solid #30363d; margin-bottom: 16px; flex-wrap: wrap;
  }}
  .tab {{
    padding: 10px 20px; cursor: pointer;
    background: transparent; border: none;
    color: #8b949e; font-size: 14px;
    border-bottom: 2px solid transparent;
  }}
  .tab.active {{
    color: #f0f6fc; border-bottom-color: #1f6feb; font-weight: 600;
  }}
  .filters {{
    display: flex; gap: 8px; margin-bottom: 12px;
    flex-wrap: wrap; align-items: center;
  }}
  .filters label {{ color: #8b949e; font-size: 12px; }}
  .filters select, .filters input {{
    background: #0d1117; color: #c9d1d9;
    border: 1px solid #30363d; border-radius: 6px;
    padding: 6px 10px; font-size: 13px;
  }}
  .filters button {{
    background: #21262d; color: #c9d1d9;
    border: 1px solid #30363d; border-radius: 6px;
    padding: 6px 12px; font-size: 12px; cursor: pointer;
  }}
  .filters button:hover {{ background: #30363d; }}
  .filters .count {{ margin-left: auto; color: #8b949e; font-size: 12px; }}
  table {{
    width: 100%; border-collapse: collapse;
    background: #161b22; border-radius: 8px; overflow: hidden;
  }}
  th {{
    background: #21262d; color: #f0f6fc;
    padding: 10px 8px; text-align: left;
    font-size: 12px; text-transform: uppercase;
    letter-spacing: 0.3px; cursor: pointer; user-select: none;
    border-bottom: 1px solid #30363d;
  }}
  th:hover {{ background: #30363d; }}
  td {{
    padding: 8px; border-bottom: 1px solid #21262d;
    font-family: "SF Mono", Menlo, monospace; font-size: 12px;
  }}
  tr:hover {{ background: #21262d; }}
  .direction {{ font-weight: 700; padding: 2px 6px; border-radius: 4px; font-size: 11px; }}
  .direction.LONG {{ color: #3fb950; background: rgba(63, 185, 80, 0.15); }}
  .direction.SHORT {{ color: #f85149; background: rgba(248, 81, 73, 0.15); }}
  .empty {{ padding: 40px; text-align: center; color: #8b949e; }}

  .log-line {{
    font-family: "SF Mono", Menlo, monospace; font-size: 12px;
    padding: 3px 8px; white-space: pre-wrap;
    border-left: 2px solid transparent;
  }}
  .log-INFO   {{ color: #8b949e; border-left-color: #30363d; }}
  .log-SIGNAL {{ color: #3fb950; border-left-color: #238636; background: rgba(63,185,80,0.04); }}
  .log-WARN   {{ color: #d29922; border-left-color: #d29922; background: rgba(210,153,34,0.04); }}
  .log-ERROR  {{ color: #f85149; border-left-color: #f85149; background: rgba(248,81,73,0.06); }}

  .log-toolbar {{
    display: flex; gap: 12px; align-items: center;
    flex-wrap: wrap; margin-bottom: 10px;
  }}
  .log-toolbar label {{ color: #c9d1d9; font-size: 12px; display: flex; align-items: center; gap: 4px; }}
  .log-container {{
    background: #161b22; border: 1px solid #30363d;
    border-radius: 8px; padding: 8px; max-height: 70vh; overflow: auto;
  }}

  .panel {{ display: none; }}
  .panel.active {{ display: block; }}
</style>
</head>
<body>
  <h1>🛰️ Bot Dashboard</h1>

  <div class="summary">
    <div class="summary-card">
      <h3>👥 Подписчики</h3>
      <p id="subs-summary">-</p>
    </div>
    <div class="summary-card">
      <h3>📡 Отправленные сигналы</h3>
      <p id="signals-summary">-</p>
    </div>
    <div class="summary-card">
      <h3>🪵 Логи</h3>
      <p id="logs-summary">-</p>
    </div>
  </div>

  <div class="tabs">
    <button class="tab active" onclick="switchTab('subs', this)">👥 Подписчики</button>
    <button class="tab" onclick="switchTab('signals', this)">📡 Сигналы</button>
    <button class="tab" onclick="switchTab('logs', this)">🪵 Логи</button>
  </div>

  <!-- ============ SUBS ============ -->
  <div class="panel active" id="panel-subs">
    <div class="filters">
      <input id="subs-search" type="text" placeholder="поиск по username/first_name/id" oninput="renderSubs()">
      <span class="count" id="subs-count"></span>
    </div>
    <div id="subs-table"></div>
  </div>

  <!-- ============ SIGNALS ============ -->
  <div class="panel" id="panel-signals">
    <div class="filters">
      <label>Стратегия:
        <select id="sig-strategy" onchange="renderSignals()">
          <option value="">Все</option>
        </select>
      </label>
      <label>Символ:
        <select id="sig-symbol" onchange="renderSignals()">
          <option value="">Все</option>
        </select>
      </label>
      <label>Направление:
        <select id="sig-direction" onchange="renderSignals()">
          <option value="">Все</option>
          <option value="LONG">🟢 LONG</option>
          <option value="SHORT">🔴 SHORT</option>
        </select>
      </label>
      <span class="count" id="sig-count"></span>
    </div>
    <div id="signals-table"></div>
  </div>

  <!-- ============ LOGS ============ -->
  <div class="panel" id="panel-logs">
    <div class="log-toolbar">
      <label><input type="checkbox" data-level="INFO"   checked onchange="renderLogs()"> INFO</label>
      <label><input type="checkbox" data-level="SIGNAL" checked onchange="renderLogs()"> SIGNAL</label>
      <label><input type="checkbox" data-level="WARN"   checked onchange="renderLogs()"> WARN</label>
      <label><input type="checkbox" data-level="ERROR"  checked onchange="renderLogs()"> ERROR</label>
      <input id="log-search" type="text" placeholder="поиск по тексту лога" oninput="renderLogs()">
      <span class="count" id="logs-count"></span>
    </div>
    <div class="log-container" id="log-container"></div>
  </div>

<script>
  const SUBS    = {subs_json};
  const SIGNALS = {signals_json};
  const LOGS    = {logs_json};

  function el(id) {{ return document.getElementById(id); }}

  // ---- summary cards ----
  el('subs-summary').textContent = `${{SUBS.length}} подписчиков`;
  el('signals-summary').textContent = `${{SIGNALS.length}} сигналов всего`;
  el('logs-summary').textContent = `${{LOGS.length}} строк (tail {LOG_TAIL_LINES})`;

  // ---- tabs ----
  function switchTab(name, btn) {{
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
    btn.classList.add('active');
    el(`panel-${{name}}`).classList.add('active');
  }}

  // ---- subs ----
  function renderSubs() {{
    const q = (el('subs-search').value || '').toLowerCase();
    const rows = SUBS.filter(u => {{
      if (!q) return true;
      const hay = `${{u.id}} ${{u.username||''}} ${{u.first_name||''}}`.toLowerCase();
      return hay.includes(q);
    }});
    el('subs-count').textContent = `${{rows.length}} из ${{SUBS.length}}`;
    if (!rows.length) {{
      el('subs-table').innerHTML = '<div class="empty">Нет подписчиков</div>';
      return;
    }}
    let html = '<table><thead><tr>';
    html += '<th>id</th><th>username</th><th>first_name</th><th>joined_at</th>';
    html += '<th>last_active</th><th>дн. с подписки</th><th>дн. с активности</th>';
    html += '</tr></thead><tbody>';
    for (const u of rows) {{
      const uname = u.username ? '@' + u.username : '';
      html += `<tr>
        <td>${{u.id}}</td>
        <td>${{uname}}</td>
        <td>${{u.first_name || ''}}</td>
        <td>${{u.joined_at || ''}}</td>
        <td>${{u.last_active || ''}}</td>
        <td>${{u.days_subscribed}}</td>
        <td>${{u.days_since_active}}</td>
      </tr>`;
    }}
    html += '</tbody></table>';
    el('subs-table').innerHTML = html;
  }}

  // ---- signals ----
  function populateSignalFilters() {{
    const strategies = [...new Set(SIGNALS.map(s => s.strategy).filter(Boolean))].sort();
    const symbols = [...new Set(SIGNALS.map(s => s.symbol).filter(Boolean))].sort();
    el('sig-strategy').innerHTML = '<option value="">Все</option>' +
      strategies.map(s => `<option value="${{s}}">${{s}}</option>`).join('');
    el('sig-symbol').innerHTML = '<option value="">Все</option>' +
      symbols.map(s => `<option value="${{s}}">${{s}}</option>`).join('');
  }}

  function renderSignals() {{
    const strat = el('sig-strategy').value;
    const sym = el('sig-symbol').value;
    const dir = el('sig-direction').value;
    let rows = SIGNALS.filter(r => {{
      if (strat && r.strategy !== strat) return false;
      if (sym && r.symbol !== sym) return false;
      if (dir && r.direction !== dir) return false;
      return true;
    }});
    rows.sort((a, b) => {{
      const av = a.sent_at || a.ob1h_cur_time || '';
      const bv = b.sent_at || b.ob1h_cur_time || '';
      return bv.localeCompare(av);
    }});
    el('sig-count').textContent = `${{rows.length}} из ${{SIGNALS.length}}`;
    if (!rows.length) {{
      el('signals-table').innerHTML = '<div class="empty">Нет сигналов</div>';
      return;
    }}
    let html = '<table><thead><tr>';
    html += '<th>strategy</th><th>symbol</th><th>source_tf</th><th>direction</th>';
    html += '<th>ob1h_cur_time</th><th>sent_at</th><th>price</th>';
    html += '</tr></thead><tbody>';
    for (const r of rows) {{
      const price = (typeof r.price === 'number') ? r.price.toFixed(2) : r.price;
      html += `<tr>
        <td><b>${{r.strategy}}</b></td>
        <td>${{r.symbol}}</td>
        <td>${{r.source_tf}}</td>
        <td><span class="direction ${{r.direction}}">${{r.direction}}</span></td>
        <td>${{r.ob1h_cur_time}}</td>
        <td>${{r.sent_at}}</td>
        <td>${{price}}</td>
      </tr>`;
    }}
    html += '</tbody></table>';
    el('signals-table').innerHTML = html;
  }}

  // ---- logs ----
  function getActiveLogLevels() {{
    const boxes = document.querySelectorAll('.log-toolbar input[type=checkbox]');
    return new Set(Array.from(boxes).filter(b => b.checked).map(b => b.dataset.level));
  }}

  function renderLogs() {{
    const levels = getActiveLogLevels();
    const q = (el('log-search').value || '').toLowerCase();
    const rows = LOGS.filter(l => {{
      if (!levels.has(l.level)) return false;
      if (q && !(l.msg.toLowerCase().includes(q) || l.ts.toLowerCase().includes(q))) return false;
      return true;
    }});
    el('logs-count').textContent = `${{rows.length}} из ${{LOGS.length}}`;
    if (!rows.length) {{
      el('log-container').innerHTML = '<div class="empty">Нет строк</div>';
      return;
    }}
    const html = rows.map(l => {{
      const safeMsg = (l.msg || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
      return `<div class="log-line log-${{l.level}}"><span>${{l.ts}}</span> [${{l.level}}] ${{safeMsg}}</div>`;
    }}).join('');
    el('log-container').innerHTML = html;
  }}

  populateSignalFilters();
  renderSubs();
  renderSignals();
  renderLogs();
</script>
</body>
</html>
"""


def main() -> None:
    subs = load_subscribers()
    signals = load_sent_signals()
    logs = load_log_lines()

    print(f"[OK] subscribers: {len(subs)}")
    print(f"[OK] sent_signals: {len(signals)}")
    print(f"[OK] log lines (tail {LOG_TAIL_LINES}): {len(logs)}")

    html = build_html(subs, signals, logs)
    OUTPUT_HTML.write_text(html, encoding="utf-8")
    size_kb = OUTPUT_HTML.stat().st_size / 1024
    print(f"[OK] HTML: {OUTPUT_HTML} ({size_kb:.0f} KB)")

    abs_path = OUTPUT_HTML.resolve()
    url = f"file://{abs_path}"
    print(f"[OK] открываю: {url}")
    webbrowser.open(url)


if __name__ == "__main__":
    main()
