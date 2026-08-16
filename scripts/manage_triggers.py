"""
List (and optionally delete) Composio trigger instances.

A disconnect/reconnect that didn't clean up leaves orphaned GMAIL_NEW_GMAIL_MESSAGE
triggers firing on the same mailbox, so one email gets ingested several times. Use
this to see every active trigger and prune the extras down to one per mailbox.

Run from the backend repo root with the app env loaded (COMPOSIO_API_KEY set):

    # List every active trigger
    python -m scripts.manage_triggers

    # Delete specific trigger instance(s) by id
    python -m scripts.manage_triggers --delete ti_abc123 ti_def456

    # Keep ONE gmail trigger, delete all the other gmail ones
    python -m scripts.manage_triggers --keep ti_abc123
"""

import argparse

from app.services.composio_client import composio, delete_trigger


def _field(item, *names, default=None):
    """Pull the first present attribute/key from an SDK item (shape varies)."""
    data = item.model_dump() if hasattr(item, "model_dump") else dict(getattr(item, "__dict__", {}))
    for n in names:
        if getattr(item, n, None) is not None:
            return getattr(item, n)
        if isinstance(data, dict) and data.get(n) is not None:
            return data[n]
    return default


def list_triggers():
    result = composio.triggers.list_active(show_disabled=True)
    items = getattr(result, "items", None) or []
    if not items:
        print("No trigger instances found.")
        return []
    print(f"{len(items)} trigger instance(s):\n")
    for i, it in enumerate(items, 1):
        tid  = _field(it, "id", "trigger_id", "uuid", default="?")
        name = _field(it, "trigger_name", "triggerName", "slug", default="?")
        acct = _field(it, "connected_account_id", "connectedAccountId", default="?")
        dis  = _field(it, "disabled", default=False)
        print(f"  [{i}] id={tid}")
        print(f"       trigger={name}  connected_account={acct}  disabled={dis}")
    print()
    return items


def main():
    ap = argparse.ArgumentParser(description="List/delete Composio trigger instances")
    ap.add_argument("--delete", nargs="+", metavar="TRIGGER_ID", help="Delete these trigger instance id(s)")
    ap.add_argument("--keep", metavar="TRIGGER_ID", help="Delete every GMAIL_NEW_GMAIL_MESSAGE trigger except this one")
    args = ap.parse_args()

    if args.delete:
        for tid in args.delete:
            try:
                delete_trigger(tid)
                print(f"deleted {tid}")
            except Exception as exc:  # noqa: BLE001
                print(f"failed to delete {tid}: {exc}")
        return

    items = list_triggers()

    if args.keep:
        gmail = [
            it for it in items
            if str(_field(it, "trigger_name", "triggerName", "slug", default="")).upper().startswith("GMAIL_NEW")
        ]
        for it in gmail:
            tid = _field(it, "id", "trigger_id", "uuid")
            if tid and tid != args.keep:
                try:
                    delete_trigger(tid)
                    print(f"deleted {tid}")
                except Exception as exc:  # noqa: BLE001
                    print(f"failed to delete {tid}: {exc}")
        print(f"kept {args.keep}")


if __name__ == "__main__":
    main()
