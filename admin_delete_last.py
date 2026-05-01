"""Удалить последнюю рассылку (broadcast) у всех получателей.

Использует state/last_broadcast.json (перезаписывается каждым broadcast()'ом).
Telegram разрешает удалять свои сообщения в течение 48 часов.

Использование:
    python admin_delete_last.py

Вывод: сколько удалено / failed.
"""
from telegram_bot import delete_last_broadcast


def main() -> None:
    res = delete_last_broadcast()
    print(f"Result: ok={res['ok']}, failed={res['failed']}, total={res['total']}")
    if res.get("errors"):
        print("Errors:")
        for cid, err in res["errors"][:10]:
            print(f"  {cid}: {err}")
    if res.get("error"):
        print(f"Top-level error: {res['error']}")


if __name__ == "__main__":
    main()
