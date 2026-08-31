from __future__ import annotations

import argparse
import getpass
import os
import sys

from .config import GatewayConfig
from .server import create_server
from .store import Catalog


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="knowledge-dump-gateway")
    commands = root.add_subparsers(dest="command")

    serve = commands.add_parser("serve", help="Run the gateway HTTP service")
    serve.add_argument("--host", default=os.environ.get("KNOWLEDGE_DUMP_GATEWAY_HOST", "127.0.0.1"))
    serve.add_argument("--port", type=int, default=int(os.environ.get("KNOWLEDGE_DUMP_GATEWAY_PORT", "8787")))

    account = commands.add_parser("account", help="Manage operator-provisioned accounts")
    account_commands = account.add_subparsers(dest="account_command", required=True)
    create = account_commands.add_parser("create", help="Create a Knowledge Dump account")
    create.add_argument("--email", required=True)
    create.add_argument("--display-name", required=True)
    create.add_argument("--plan", default="Personal")
    create.add_argument("--password-stdin", action="store_true")
    create.add_argument("--seed-workspace", action="store_true")

    commands.add_parser("database-status", help="Show the configured database backend")
    return root


def main() -> None:
    arguments = parser().parse_args()
    command = arguments.command or "serve"
    config = GatewayConfig.from_env()
    if command == "serve":
        host = getattr(arguments, "host", os.environ.get("KNOWLEDGE_DUMP_GATEWAY_HOST", "127.0.0.1"))
        port = getattr(arguments, "port", int(os.environ.get("KNOWLEDGE_DUMP_GATEWAY_PORT", "8787")))
        server = create_server(host=host, port=port, config=config)
        print(
            f"Knowledge Dump gateway listening on http://{host}:{port} "
            f"({server.catalog.config.mode}, {server.catalog.database_backend})",
            flush=True,
        )
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
        return

    catalog = Catalog(config=config, bootstrap_demo=False)
    if command == "database-status":
        print(f"mode={config.mode} backend={catalog.database_backend} url={_safe_database_url(config.database_url)}")
        return
    if command == "account" and arguments.account_command == "create":
        password = sys.stdin.readline().rstrip("\n") if arguments.password_stdin else getpass.getpass("Password: ")
        account = catalog.create_account(
            email=arguments.email,
            password=password,
            display_name=arguments.display_name,
            plan=arguments.plan,
            seed_workspace=arguments.seed_workspace,
        )
        print(f"Created {account['id']} for {account['email']}")


def _safe_database_url(database_url: str) -> str:
    if "@" not in database_url or "://" not in database_url:
        return database_url
    scheme, remainder = database_url.split("://", 1)
    return f"{scheme}://***@{remainder.split('@', 1)[1]}"


if __name__ == "__main__":
    main()
