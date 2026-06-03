# Claude Memory Export

Экспорт personal Claude memory из `~/.claude/projects/-Users-vadim/memory/`
для архивирования в проектный git.

**Источник:** `~/.claude/projects/-Users-vadim/memory/` (живёт ВНЕ traid-bot, в Claude config)
**Эта папка:** snapshot для backup + share + cross-machine.

## Структура

`MEMORY.md` — главный index. Содержит ссылки на остальные файлы (короткое описание каждого).
Остальные `*.md` — отдельные memory entries.

## Типы memory

| Type | Назначение |
|---|---|
| `user` | Информация о пользователе (роль, expertise) |
| `feedback` | Правила работы / каноны / corrections |
| `project` | Текущие задачи, состояния, decisions проектов |
| `reference` | Ссылки на внешние ресурсы |

## Sync convention

При завершении сессии (если пользователь говорит «сохрани memory в repo»):

```bash
cp ~/.claude/projects/-Users-vadim/memory/*.md \
   ~/traid-bot/vault/knowledge/claude-memory/
```

## Что НЕ сохранять

- ML model artifacts (CSV, parquet, pickle) — отдельно
- Temporary debug entries
- Outdated entries (regularly cleanup)

## Latest snapshot

Date: см. last commit в этой папке.
