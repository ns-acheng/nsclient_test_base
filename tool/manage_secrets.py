"""
CLI for managing encrypted local secrets.

Usage:
    python tool/manage_secrets.py init              # Generate the key (first-time setup)
    python tool/manage_secrets.py set <name>        # Prompt for value and encrypt
    python tool/manage_secrets.py get <name>        # Decrypt and print
    python tool/manage_secrets.py list              # List stored secret names
    python tool/manage_secrets.py delete <name>     # Remove a secret
    python tool/manage_secrets.py info              # Show key path and store path

Well-known secret names:
    confluence_api_token
    install_token
    org_key
    enroll_auth_token
    enroll_encryption_token
    uninstall_password
"""

import argparse
import getpass
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from util_log import setup_logging
from util_secrets import (
    SECRET_CONFLUENCE_API_TOKEN,
    SECRET_ENROLL_AUTH_TOKEN,
    SECRET_ENROLL_ENCRYPTION_TOKEN,
    SECRET_INSTALL_TOKEN,
    SECRET_ORG_KEY,
    SECRET_UNINSTALL_PASSWORD,
    delete_secret,
    get_secret,
    init_key,
    key_path,
    list_secrets,
    store_secret,
    _STORE_FILE,
)

log = logging.getLogger(__name__)

_KNOWN_SECRETS = {
    SECRET_CONFLUENCE_API_TOKEN:    "Confluence API token (for fetch_test_plan.py)",
    SECRET_INSTALL_TOKEN:           "NSClient install token (msiexec token=...)",
    SECRET_ORG_KEY:                 "Org key for Linux .run installer (-o flag)",
    SECRET_ENROLL_AUTH_TOKEN:       "IDP enroll auth token (enrollauthtoken=...)",
    SECRET_ENROLL_ENCRYPTION_TOKEN: "IDP enroll encryption token (enrollencryptiontoken=...)",
    SECRET_UNINSTALL_PASSWORD:      "NSClient uninstall password (if protection enabled)",
}


# ── Sub-commands ──────────────────────────────────────────────────────────────

def cmd_init(args: argparse.Namespace) -> int:
    key = init_key(force=getattr(args, "force", False))
    print(f"Key file: {key}")
    print(f"Secrets store: {_STORE_FILE}")
    print("Ready. Use 'set <name>' to store secrets.")
    return 0


def cmd_set(args: argparse.Namespace) -> int:
    name = args.name.strip()
    if not name:
        print("Error: secret name cannot be empty", file=sys.stderr)
        return 2

    # Use getpass to avoid echoing sensitive input to the terminal
    try:
        value = getpass.getpass(f"Value for '{name}': ")
    except (KeyboardInterrupt, EOFError):
        print("\nAborted.", file=sys.stderr)
        return 1

    if not value:
        print("Error: value cannot be empty", file=sys.stderr)
        return 2

    store_secret(name, value)
    print(f"Stored: {name}")
    return 0


def cmd_get(args: argparse.Namespace) -> int:
    value = get_secret(args.name)
    if value is None:
        print(f"Not found: {args.name}", file=sys.stderr)
        return 1
    print(value)
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    names = list_secrets()
    if not names:
        print("No secrets stored.")
        return 0

    print(f"Stored secrets ({len(names)}):")
    for name in sorted(names):
        description = _KNOWN_SECRETS.get(name, "")
        tag = f"  — {description}" if description else ""
        print(f"  {name}{tag}")
    return 0


def cmd_delete(args: argparse.Namespace) -> int:
    name = args.name
    confirm = input(f"Delete '{name}'? [y/N] ").strip().lower()
    if confirm != "y":
        print("Cancelled.")
        return 0
    if delete_secret(name):
        print(f"Deleted: {name}")
        return 0
    print(f"Not found: {name}", file=sys.stderr)
    return 1


def cmd_info(args: argparse.Namespace) -> int:
    kp = key_path()
    print(f"Key file  : {kp}  {'(exists)' if kp.exists() else '(MISSING — run init)'}")
    print(f"Store file: {_STORE_FILE}  {'(exists)' if _STORE_FILE.exists() else '(empty)'}")
    print()
    print("Well-known secret names:")
    for name, desc in _KNOWN_SECRETS.items():
        print(f"  {name:<32} {desc}")
    return 0


# ── CLI ──────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Manage encrypted local secrets for nsclient_test_base.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Debug logging")
    sub = parser.add_subparsers(dest="command", required=True)

    # init
    p_init = sub.add_parser("init", help="Generate the local secret key (first-time setup)")
    p_init.add_argument("--force", action="store_true",
                        help="Overwrite existing key (WARNING: existing secrets become unreadable)")

    # set
    p_set = sub.add_parser("set", help="Encrypt and store a secret value")
    p_set.add_argument("name", help="Secret name (e.g. confluence_api_token)")

    # get
    p_get = sub.add_parser("get", help="Decrypt and print a secret value")
    p_get.add_argument("name", help="Secret name")

    # list
    sub.add_parser("list", help="List all stored secret names")

    # delete
    p_del = sub.add_parser("delete", help="Remove a secret")
    p_del.add_argument("name", help="Secret name")

    # info
    sub.add_parser("info", help="Show key path, store path, and known secret names")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    setup_logging(verbose=args.verbose)

    commands = {
        "init":   cmd_init,
        "set":    cmd_set,
        "get":    cmd_get,
        "list":   cmd_list,
        "delete": cmd_delete,
        "info":   cmd_info,
    }
    return commands[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
