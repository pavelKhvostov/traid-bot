"""
generate_report.py
Читает signals/backtest_<strategy>.csv для 5 стратегий (obx4, fvg, ob_htf,
rdrb, fractal), генерирует signals_report.html с интерактивной таблицей:
5 вкладок, фильтры, сортировка, пагинация, ссылки в TradingView, копирование
времени в буфер.

Запуск:
    python generate_report.py
"""

import csv
import json
import webbrowser
from pathlib import Path

SIGNALS_DIR = Path("signals")
OUTPUT_HTML = Path("signals_report.html")

STRATEGIES = [
    # (key, label, icon, csv_name)
    ("obx4",    "OBX4",    "⚡", "backtest_obx4.csv"),
    ("fvg",     "FVG",     "🎯", "backtest_fvg.csv"),
    ("ob_htf",  "OB_HTF",  "🟣", "backtest_ob_htf.csv"),
    ("rdrb",    "RDRB",    "⚪", "backtest_rdrb.csv"),
    ("fractal", "FRACTAL", "🔱", "backtest_fractal.csv"),
]


def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        print(f"[SKIP] {path} не найден")
        return []
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            for num_col in ("zone_bottom", "zone_top", "ob1h_cur_close", "zone_age_hours"):
                if num_col in row and row[num_col]:
                    try:
                        row[num_col] = float(row[num_col])
                    except ValueError:
                        pass
            rows.append(row)
    print(f"[OK] {path}: {len(rows)} строк")
    return rows


def summary_line(rows: list[dict], name: str) -> str:
    if not rows:
        return f"{name}: нет данных"
    by_symbol: dict[str, int] = {}
    for r in rows:
        s = r.get("symbol", "?")
        by_symbol[s] = by_symbol.get(s, 0) + 1
    parts = [f"{k}={v}" for k, v in sorted(by_symbol.items())]
    return f"{name}: {len(rows)} сигналов ({', '.join(parts)})"


def build_html(data_by_key: dict[str, list[dict]]) -> str:
    data_json = json.dumps(data_by_key, ensure_ascii=False, default=str)

    summary_cards = "\n".join(
        f'''    <div class="summary-card">
      <h3>{icon} {label} стратегия</h3>
      <p id="{key}-summary">Загрузка...</p>
    </div>'''
        for key, label, icon, _ in STRATEGIES
    )

    tabs = "\n".join(
        f'    <button class="tab{" active" if idx == 0 else ""}" '
        f'onclick="switchTab(\'{key}\', this)">{icon} {label}</button>'
        for idx, (key, label, icon, _) in enumerate(STRATEGIES)
    )

    # первая вкладка по умолчанию
    default_tab = STRATEGIES[0][0]

    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<title>Trading Signals Report</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    padding: 20px;
    background: #0d1117;
    color: #c9d1d9;
    font-family: -apple-system, "SF Pro Text", "Segoe UI", sans-serif;
    font-size: 14px;
  }}
  h1 {{ color: #f0f6fc; margin: 0 0 16px 0; }}
  .summary {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
    gap: 12px;
    margin-bottom: 16px;
  }}
  .summary-card {{
    background: #161b22;
    border: 1px solid #30363d;
    border-radius: 8px;
    padding: 12px 16px;
  }}
  .summary-card h3 {{ margin: 0 0 6px 0; color: #58a6ff; font-size: 14px; }}
  .summary-card p {{ margin: 0; color: #8b949e; font-size: 12px; }}
  .tabs {{
    display: flex;
    gap: 4px;
    border-bottom: 1px solid #30363d;
    margin-bottom: 16px;
    flex-wrap: wrap;
  }}
  .tab {{
    padding: 10px 20px;
    cursor: pointer;
    background: transparent;
    border: none;
    color: #8b949e;
    font-size: 14px;
    border-bottom: 2px solid transparent;
  }}
  .tab.active {{
    color: #f0f6fc;
    border-bottom-color: #1f6feb;
    font-weight: 600;
  }}
  .filters {{
    display: flex;
    gap: 8px;
    margin-bottom: 12px;
    flex-wrap: wrap;
    align-items: center;
  }}
  .filters label {{ color: #8b949e; font-size: 12px; }}
  .filters select, .filters input {{
    background: #0d1117;
    color: #c9d1d9;
    border: 1px solid #30363d;
    border-radius: 6px;
    padding: 6px 10px;
    font-size: 13px;
  }}
  .filters button {{
    background: #21262d;
    color: #c9d1d9;
    border: 1px solid #30363d;
    border-radius: 6px;
    padding: 6px 12px;
    font-size: 12px;
    cursor: pointer;
  }}
  .filters button:hover {{ background: #30363d; }}
  .filters .count {{
    margin-left: auto;
    color: #8b949e;
    font-size: 12px;
  }}
  table {{
    width: 100%;
    border-collapse: collapse;
    background: #161b22;
    border-radius: 8px;
    overflow: hidden;
  }}
  th {{
    background: #21262d;
    color: #f0f6fc;
    padding: 10px 8px;
    text-align: left;
    font-size: 12px;
    text-transform: uppercase;
    letter-spacing: 0.3px;
    cursor: pointer;
    user-select: none;
    border-bottom: 1px solid #30363d;
  }}
  th:hover {{ background: #30363d; }}
  td {{
    padding: 8px;
    border-bottom: 1px solid #21262d;
    font-family: "SF Mono", Menlo, monospace;
    font-size: 12px;
  }}
  tr.long {{ background: rgba(35, 134, 54, 0.08); }}
  tr.short {{ background: rgba(218, 54, 51, 0.08); }}
  tr:hover {{ background: #21262d !important; }}
  .direction {{
    font-weight: 700;
    padding: 2px 6px;
    border-radius: 4px;
    font-size: 11px;
  }}
  .direction.LONG {{ color: #3fb950; background: rgba(63, 185, 80, 0.15); }}
  .direction.SHORT {{ color: #f85149; background: rgba(248, 81, 73, 0.15); }}
  .tv-btn {{
    background: #1f6feb;
    color: white;
    border: none;
    padding: 4px 10px;
    border-radius: 4px;
    cursor: pointer;
    font-size: 11px;
    text-decoration: none;
    display: inline-block;
  }}
  .tv-btn:hover {{ background: #1158c7; }}
  .copy-btn {{
    background: #30363d;
    color: #c9d1d9;
    border: none;
    padding: 4px 10px;
    border-radius: 4px;
    cursor: pointer;
    font-size: 11px;
    margin-left: 4px;
  }}
  .copy-btn:hover {{ background: #484f58; }}
  .copy-btn.copied {{ background: #238636; color: white; }}
  .pagination {{
    display: flex;
    gap: 4px;
    margin-top: 16px;
    justify-content: center;
    align-items: center;
    flex-wrap: wrap;
  }}
  .pagination button {{
    background: #21262d;
    color: #c9d1d9;
    border: 1px solid #30363d;
    border-radius: 4px;
    padding: 6px 12px;
    cursor: pointer;
    font-size: 12px;
    min-width: 32px;
  }}
  .pagination button.active {{
    background: #1f6feb;
    color: white;
    border-color: #1f6feb;
  }}
  .pagination button:hover:not(.active) {{ background: #30363d; }}
  .pagination span {{ color: #8b949e; font-size: 12px; margin: 0 8px; }}
  .empty {{
    padding: 40px;
    text-align: center;
    color: #8b949e;
  }}
  .hint {{
    color: #8b949e;
    font-size: 12px;
    margin-top: 8px;
    padding: 12px;
    background: #161b22;
    border-radius: 6px;
    border-left: 3px solid #1f6feb;
  }}
</style>
</head>
<body>
  <h1>📊 Trading Signals — Backtest Report</h1>

  <div class="summary">
{summary_cards}
  </div>

  <div class="tabs">
{tabs}
  </div>

  <div class="filters">
    <label>Символ:</label>
    <select id="filter-symbol" onchange="applyFilters()">
      <option value="">Все</option>
    </select>

    <label>Таймфрейм:</label>
    <select id="filter-tf" onchange="applyFilters()">
      <option value="">Все</option>
    </select>

    <label>Направление:</label>
    <select id="filter-direction" onchange="applyFilters()">
      <option value="">Все</option>
      <option value="LONG">🟢 LONG</option>
      <option value="SHORT">🔴 SHORT</option>
    </select>

    <button onclick="resetFilters()">Сбросить</button>

    <span class="count" id="row-count"></span>
  </div>

  <div class="hint">
    💡 <b>Как сверять в TradingView:</b> нажми кнопку "TV" — откроется график нужного символа и ТФ.
    Потом в TradingView нажми <kbd>Alt+G</kbd> (на Mac <kbd>Option+G</kbd>), вставь скопированное время и Enter — график перейдёт на нужную свечу.
    Кнопка "📋" копирует время в буфер.
  </div>

  <div id="table-container"></div>

  <div class="pagination" id="pagination"></div>

<script>
  const DATA = {data_json};
  const STRATS = {json.dumps([{"key": k, "label": l} for k, l, _, _ in STRATEGIES], ensure_ascii=False)};

  let currentTab = '{default_tab}';
  let filtered = [];
  let currentPage = 1;
  const PAGE_SIZE = 100;
  let sortCol = 'ob1h_cur_time_utc';
  let sortDir = 'desc';

  const TF_TO_TV = {{
    '1h': '60', '2h': '120', '3h': '180', '4h': '240',
    '6h': '360', '8h': '480', '12h': '720',
    '1d': 'D', '2d': '2D', '3d': '3D',
  }};

  function summaryText(rows, name) {{
    if (!rows || !rows.length) return `${{name}}: нет данных`;
    const bySym = {{}};
    for (const r of rows) bySym[r.symbol] = (bySym[r.symbol] || 0) + 1;
    const parts = Object.entries(bySym).sort().map(([k, v]) => `${{k}}=${{v}}`);
    return `${{rows.length}} сигналов (${{parts.join(', ')}})`;
  }}

  for (const s of STRATS) {{
    const el = document.getElementById(`${{s.key}}-summary`);
    if (el) el.textContent = summaryText(DATA[s.key] || [], s.label);
  }}

  function populateFilterOptions() {{
    const data = DATA[currentTab] || [];
    const symbols = [...new Set(data.map(r => r.symbol))].sort();
    const tfs = [...new Set(data.map(r => r.source_tf))].sort((a, b) => {{
      const order = ['1h','2h','3h','4h','6h','8h','12h','1d','2d','3d'];
      return order.indexOf(a) - order.indexOf(b);
    }});

    const symSelect = document.getElementById('filter-symbol');
    const tfSelect = document.getElementById('filter-tf');

    symSelect.innerHTML = '<option value="">Все</option>' +
      symbols.map(s => `<option value="${{s}}">${{s}}</option>`).join('');
    tfSelect.innerHTML = '<option value="">Все</option>' +
      tfs.map(t => `<option value="${{t}}">${{t}}</option>`).join('');
  }}

  function applyFilters() {{
    const sym = document.getElementById('filter-symbol').value;
    const tf = document.getElementById('filter-tf').value;
    const dir = document.getElementById('filter-direction').value;

    filtered = (DATA[currentTab] || []).filter(r => {{
      if (sym && r.symbol !== sym) return false;
      if (tf && r.source_tf !== tf) return false;
      if (dir && r.direction !== dir) return false;
      return true;
    }});

    sortData();
    currentPage = 1;
    render();
  }}

  function sortData() {{
    filtered.sort((a, b) => {{
      let av = a[sortCol];
      let bv = b[sortCol];
      if (typeof av === 'number' && typeof bv === 'number') {{
        return sortDir === 'asc' ? av - bv : bv - av;
      }}
      av = String(av || '');
      bv = String(bv || '');
      return sortDir === 'asc' ? av.localeCompare(bv) : bv.localeCompare(av);
    }});
  }}

  function setSort(col) {{
    if (sortCol === col) {{
      sortDir = sortDir === 'asc' ? 'desc' : 'asc';
    }} else {{
      sortCol = col;
      sortDir = 'desc';
    }}
    sortData();
    render();
  }}

  function fmtTime(iso) {{
    if (!iso) return '';
    return iso.replace('T', ' ').replace('+00:00', '').replace(/:\\d\\d$/, '');
  }}

  function copyToClipboard(text, btn) {{
    navigator.clipboard.writeText(text);
    btn.classList.add('copied');
    btn.textContent = '✓';
    setTimeout(() => {{
      btn.classList.remove('copied');
      btn.textContent = '📋';
    }}, 1200);
  }}

  function tvUrl(symbol, tf) {{
    const interval = TF_TO_TV[tf] || '240';
    return `https://www.tradingview.com/chart/?symbol=BINANCE:${{symbol}}&interval=${{interval}}`;
  }}

  function render() {{
    const container = document.getElementById('table-container');
    document.getElementById('row-count').textContent =
      `${{filtered.length}} сигналов`;

    if (!filtered.length) {{
      container.innerHTML = '<div class="empty">Нет сигналов с такими фильтрами</div>';
      document.getElementById('pagination').innerHTML = '';
      return;
    }}

    const start = (currentPage - 1) * PAGE_SIZE;
    const page = filtered.slice(start, start + PAGE_SIZE);

    const arrow = (col) => {{
      if (sortCol !== col) return '';
      return sortDir === 'asc' ? ' ↑' : ' ↓';
    }};

    let html = '<table><thead><tr>';
    html += `<th onclick="setSort('ob1h_cur_time_utc')">OB 1h время${{arrow('ob1h_cur_time_utc')}}</th>`;
    html += `<th onclick="setSort('symbol')">Символ${{arrow('symbol')}}</th>`;
    html += `<th onclick="setSort('source_tf')">ТФ зоны${{arrow('source_tf')}}</th>`;
    html += `<th onclick="setSort('direction')">Напр.${{arrow('direction')}}</th>`;
    html += `<th onclick="setSort('zone_bottom')">Зона${{arrow('zone_bottom')}}</th>`;
    html += `<th onclick="setSort('ob1h_cur_close')">Цена${{arrow('ob1h_cur_close')}}</th>`;
    html += `<th onclick="setSort('trigger_time_utc')">Зона создана${{arrow('trigger_time_utc')}}</th>`;
    html += `<th onclick="setSort('zone_age_hours')">Возраст, ч${{arrow('zone_age_hours')}}</th>`;
    html += `<th>Действия</th>`;
    html += '</tr></thead><tbody>';

    for (const r of page) {{
      const dirClass = r.direction === 'LONG' ? 'long' : 'short';
      const price = typeof r.ob1h_cur_close === 'number' ? r.ob1h_cur_close.toFixed(2) : r.ob1h_cur_close;
      const zb = typeof r.zone_bottom === 'number' ? r.zone_bottom.toFixed(4) : r.zone_bottom;
      const zt = typeof r.zone_top === 'number' ? r.zone_top.toFixed(4) : r.zone_top;
      const age = typeof r.zone_age_hours === 'number' ? r.zone_age_hours.toFixed(1) : r.zone_age_hours;
      const obTime = fmtTime(r.ob1h_cur_time_utc);
      const trigTime = fmtTime(r.trigger_time_utc);

      html += `<tr class="${{dirClass}}">`;
      html += `<td>${{obTime}}</td>`;
      html += `<td><b>${{r.symbol}}</b></td>`;
      html += `<td>${{r.source_tf}}</td>`;
      html += `<td><span class="direction ${{r.direction}}">${{r.direction}}</span></td>`;
      html += `<td>${{zb}} – ${{zt}}</td>`;
      html += `<td>${{price}}</td>`;
      html += `<td>${{trigTime}}</td>`;
      html += `<td>${{age}}</td>`;
      html += `<td>`;
      html += `<a class="tv-btn" href="${{tvUrl(r.symbol, r.source_tf)}}" target="_blank">TV</a>`;
      html += `<button class="copy-btn" onclick="copyToClipboard('${{obTime}}', this)" title="Скопировать OB 1h время">📋</button>`;
      html += `</td>`;
      html += `</tr>`;
    }}

    html += '</tbody></table>';
    container.innerHTML = html;

    renderPagination();
  }}

  function renderPagination() {{
    const total = Math.ceil(filtered.length / PAGE_SIZE);
    const el = document.getElementById('pagination');
    if (total <= 1) {{ el.innerHTML = ''; return; }}

    let html = '';
    html += `<button onclick="gotoPage(1)" ${{currentPage === 1 ? 'disabled' : ''}}>«</button>`;
    html += `<button onclick="gotoPage(${{currentPage - 1}})" ${{currentPage === 1 ? 'disabled' : ''}}>‹</button>`;

    const maxButtons = 7;
    let from = Math.max(1, currentPage - Math.floor(maxButtons / 2));
    let to = Math.min(total, from + maxButtons - 1);
    from = Math.max(1, to - maxButtons + 1);

    if (from > 1) html += `<span>...</span>`;
    for (let i = from; i <= to; i++) {{
      html += `<button onclick="gotoPage(${{i}})" class="${{i === currentPage ? 'active' : ''}}">${{i}}</button>`;
    }}
    if (to < total) html += `<span>...</span>`;

    html += `<button onclick="gotoPage(${{currentPage + 1}})" ${{currentPage === total ? 'disabled' : ''}}>›</button>`;
    html += `<button onclick="gotoPage(${{total}})" ${{currentPage === total ? 'disabled' : ''}}>»</button>`;
    html += `<span>Страница ${{currentPage}} из ${{total}}</span>`;

    el.innerHTML = html;
  }}

  function gotoPage(n) {{
    const total = Math.ceil(filtered.length / PAGE_SIZE);
    if (n < 1 || n > total) return;
    currentPage = n;
    render();
    window.scrollTo({{ top: 0, behavior: 'smooth' }});
  }}

  function switchTab(tab, btn) {{
    currentTab = tab;
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    btn.classList.add('active');
    resetFilters();
  }}

  function resetFilters() {{
    document.getElementById('filter-symbol').value = '';
    document.getElementById('filter-tf').value = '';
    document.getElementById('filter-direction').value = '';
    populateFilterOptions();
    applyFilters();
  }}

  populateFilterOptions();
  applyFilters();
</script>
</body>
</html>
"""


def main():
    if not SIGNALS_DIR.exists():
        print(f"[ERR] папка {SIGNALS_DIR} не существует — сначала запусти full_backtest_new.py")
        return

    data_by_key: dict[str, list[dict]] = {}
    for key, label, _, csv_name in STRATEGIES:
        rows = read_csv(SIGNALS_DIR / csv_name)
        data_by_key[key] = rows

    if not any(data_by_key.values()):
        print("[ERR] все CSV пусты или отсутствуют")
        return

    print()
    for key, label, _, _ in STRATEGIES:
        print(summary_line(data_by_key[key], label))
    print()

    html = build_html(data_by_key)
    OUTPUT_HTML.write_text(html, encoding="utf-8")

    size_kb = OUTPUT_HTML.stat().st_size / 1024
    print(f"[OK] HTML сгенерирован: {OUTPUT_HTML} ({size_kb:.0f} KB)")

    abs_path = OUTPUT_HTML.resolve()
    url = f"file://{abs_path}"
    print(f"[OK] открываю в браузере: {url}")
    webbrowser.open(url)


if __name__ == "__main__":
    main()
