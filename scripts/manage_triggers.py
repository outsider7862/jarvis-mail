"""
Inspect and prune Composio triggers and connected accounts.

Repeated Gmail connect/disconnect cycles pile up (a) orphaned
GMAIL_NEW_GMAIL_MESSAGE triggers — each one re-ingests every email — and (b)
stale 'ca_...' connected accounts. This lists both and lets you delete the extras.

Run from the backend repo root with the app env loaded (COMPOSIO_API_KEY set):

    # Triggers
    python -m scripts.manage_triggers                       # list active triggers
    python -m scripts.manage_triggers --delete ti_a ti_b    # delete trigger id(s)
    python -m scripts.manage_triggers --keep ti_a           # keep one gmail trigger, delete the rest

    # Connected accounts
    python -m scripts.manage_triggers --accounts            # list gmail connected accounts
    python -m scripts.manage_triggers --delete-account ca_a ca_b   # delete connection(s)
    python -m scripts.manage_triggers --keep-account ca_a   # keep one gmail connection, delete the rest

Deletions are permanent. Deleting a connection also kills any trigger on it and
signs that mailbox out — the user must reconnect. Prefer --keep-* so you don't
have to enumerate ids by hand.
"""

import argparse
import json
import re

from app.services.composio_client import composio, delete_connected_account, delete_trigger

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


def _dump(item) -> dict:
    if hasattr(item, "model_dump"):
        try:
            return item.model_dump()
        except Exception:  # noqa: BLE001
            pass
    return dict(getattr(item, "__dict__", {}))


def _field(item, *names, default=None):
    data = _dump(item)
    for n in names:
        if getattr(item, n, None) is not None:
            return getattr(item, n)
        if data.get(n) is not None:
            return data[n]
    return default


def _find_email(item) -> str:
    """Best-effort: the email isn't a stable field, so scan the blob for one."""
    m = _EMAIL_RE.search(json.dumps(_dump(item), default=str))
    return m.group(0) if m else "?"


# ── Triggers ──────────────────────────────────────────────────────────────────

def list_triggers():
    result = composio.triggers.list_active(show_disabled=True)
    items = getattr(result, "items", None) or []
    if not items:
        print("No trigger instances found.")
        return []
    print(f"{len(items)} trigger instance(s):\n")
    for i, it in enumerate(items, 1):
        print(f"  [{i}] id={_field(it, 'id', 'trigger_id', 'uuid', default='?')}")
        print(f"       trigger={_field(it, 'trigger_name', 'triggerName', 'slug', default='?')}"
              f"  connected_account={_field(it, 'connected_account_id', 'connectedAccountId', default='?')}"
              f"  disabled={_field(it, 'disabled', default=False)}")
    print()
    return items


# ── Connected accounts ────────────────────────────────────────────────────────

def list_accounts(user_filter: str | None = None):
    result = composio.connected_accounts.list(toolkit_slugs=["gmail"])
    items = getattr(result, "items", None) or []
    if user_filter:
        items = [it for it in items if _field(it, "user_id", "userId") == user_filter]
    if not items:
        print("No connected accounts found." + (f" (user {user_filter})" if user_filter else ""))
        return []
    print(f"{len(items)} gmail connected account(s)"
          + (f" for user {user_filter}" if user_filter else "") + ":\n")
    for i, it in enumerate(items, 1):
        print(f"  [{i}] id={_field(it, 'id', default='?')}"
              f"  status={_field(it, 'status', default='?')}"
              f"  email={_find_email(it)}")
        print(f"       user_id={_field(it, 'user_id', 'userId', default='?')}"
              f"  created={_field(it, 'created_at', 'createdAt', default='?')}")
    print()
    return items


def _delete_all_but(items, keep_id, id_names, delete_fn, label):
    for it in items:
        tid = _field(it, *id_names)
        if tid and tid != keep_id:
            try:
                delete_fn(tid)
                print(f"deleted {label} {tid}")
            except Exception as exc:  # noqa: BLE001
                print(f"failed to delete {label} {tid}: {exc}")
    print(f"kept {label} {keep_id}")


def main():
    ap = argparse.ArgumentParser(description="List/delete Composio triggers and connected accounts")
    ap.add_argument("--accounts", action="store_true", help="List gmail connected accounts instead of triggers")
    ap.add_argument("--user", metavar="USER_ID", help="Filter the account list to one Supabase user_id")
    ap.add_argument("--delete", nargs="+", metavar="TRIGGER_ID", help="Delete trigger instance id(s)")
    ap.add_argument("--keep", metavar="TRIGGER_ID", help="Delete every gmail trigger except this one")
    ap.add_argument("--delete-account", nargs="+", metavar="CA_ID", help="Delete connected account(s) by 'ca_...' id")
    ap.add_argument("--keep-account", metavar="CA_ID",
                    help="Delete the OTHER gmail connections belonging to the same user as this one (safe: never touches other users)")
    args = ap.parse_args()

    if args.delete:
        for tid in args.delete:
            try:
                delete_trigger(tid)
                print(f"deleted trigger {tid}")
            except Exception as exc:  # noqa: BLE001
                print(f"failed to delete trigger {tid}: {exc}")
        return

    if args.delete_account:
        for cid in args.delete_account:
            try:
                delete_connected_account(cid)
                print(f"deleted account {cid}")
            except Exception as exc:  # noqa: BLE001
                print(f"failed to delete account {cid}: {exc}")
        return

    if args.keep_account:
        all_items = list_accounts()
        keep = next((it for it in all_items if _field(it, "id") == args.keep_account), None)
        if keep is None:
            print(f"account {args.keep_account} not found — nothing deleted")
            return
        # Scope strictly to the kept account's own user so other users are never touched.
        owner = _field(keep, "user_id", "userId")
        same_user = [it for it in all_items if _field(it, "user_id", "userId") == owner]
        print(f"pruning user {owner}: {len(same_user)} connection(s), keeping {args.keep_account}\n")
        _delete_all_but(same_user, args.keep_account, ("id",), delete_connected_account, "account")
        return

    if args.keep:
        items = list_triggers()
        gmail = [
            it for it in items
            if str(_field(it, "trigger_name", "triggerName", "slug", default="")).upper().startswith("GMAIL_NEW")
        ]
        _delete_all_but(gmail, args.keep, ("id", "trigger_id", "uuid"), delete_trigger, "trigger")
        return

    list_accounts(args.user) if args.accounts else list_triggers()


if __name__ == "__main__":
    main()
