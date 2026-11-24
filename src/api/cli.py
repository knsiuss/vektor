"""Administrative CLI for per-user API keys.

Usage (from the project root):
    uv run python -m api.cli create-key --tenant acme --user alice --roles admin
    uv run python -m api.cli list-keys [--tenant acme]
    uv run python -m api.cli revoke-key <key-id>
"""

import argparse
import asyncio
import getpass
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path

from core.config.settings import get_settings
from core.database import create_engine, create_session_factory, init_db
from modules.conversations import models as _conversation_models  # noqa: F401
from modules.identity import models as _identity_models  # noqa: F401
from modules.identity.principal import VALID_ROLES, hash_api_key
from modules.identity.repository import ApiKeyRepository
from modules.knowledge import models as _knowledge_models  # noqa: F401
from modules.usage import models as _usage_models  # noqa: F401


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="vektor-keys", description="Manage Vektor API keys.")
    sub = parser.add_subparsers(dest="command", required=True)

    create = sub.add_parser("create-key", help="Create a per-user API key (shown once).")
    create.add_argument("--tenant", required=True)
    create.add_argument("--user", required=True)
    create.add_argument("--roles", default="member", help="Comma-separated: member,admin")
    create.add_argument("--label", default=None)
    create.add_argument("--days", type=int, default=None, help="Expire after N days.")

    listing = sub.add_parser("list-keys", help="List keys (hashes are never shown).")
    listing.add_argument("--tenant", default=None)

    revoke = sub.add_parser("revoke-key", help="Revoke a key by its id.")
    revoke.add_argument("key_id")

    setup_cmd = sub.add_parser("setup", help="Interactive wizard to write .env provider settings.")
    setup_cmd.add_argument("--env-file", default=".env")

    model_cmd = sub.add_parser("model", help="Set default chat or embedding model in .env.")
    model_cmd.add_argument("model_id")
    model_cmd.add_argument("--embedding", action="store_true", help="Set embedding model instead.")
    model_cmd.add_argument("--env-file", default=".env")
    return parser


def _upsert_env_file(env_path: Path, updates: dict[str, str]) -> None:
    lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
    remaining = dict(updates)
    new_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in remaining:
                new_lines.append(f"{key}={remaining.pop(key)}")
                continue
        new_lines.append(line)
    for key, val in remaining.items():
        new_lines.append(f"{key}={val}")
    env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


def _run_sync(args: argparse.Namespace) -> int | None:
    if args.command == "setup":
        provider = (
            input("Provider [openrouter/openai/custom] (openrouter): ").strip() or "openrouter"
        )
        base_url = (
            input("Base URL (https://openrouter.ai/api/v1): ").strip()
            or "https://openrouter.ai/api/v1"
        )
        model = input("Default chat model (openai/gpt-4o-mini): ").strip() or "openai/gpt-4o-mini"
        api_key = getpass.getpass("API Key (leave blank to keep unchanged): ").strip()
        updates = {
            "VEKTOR_LLM_PROVIDER_NAME": provider,
            "VEKTOR_LLM_BASE_URL": base_url,
            "VEKTOR_LLM_DEFAULT_MODEL": model,
        }
        if api_key:
            updates["VEKTOR_LLM_API_KEY"] = api_key
        _upsert_env_file(Path(args.env_file), updates)
        print(f"Updated {args.env_file}.")
        return 0

    if args.command == "model":
        key = "VEKTOR_LLM_EMBEDDING_MODEL" if args.embedding else "VEKTOR_LLM_DEFAULT_MODEL"
        _upsert_env_file(Path(args.env_file), {key: args.model_id.strip()})
        print(f"Updated {key} in {args.env_file}.")
        return 0

    return None


async def _run(args: argparse.Namespace) -> int:
    settings = get_settings()
    engine = create_engine(settings.database_url)
    try:
        if settings.db_auto_create:
            await init_db(engine)
        factory = create_session_factory(engine)
        async with factory() as session:
            repo = ApiKeyRepository(session)

            if args.command == "create-key":
                roles = {item.strip() for item in args.roles.split(",") if item.strip()}
                unknown = roles - VALID_ROLES
                if unknown:
                    print(f"Unknown role(s): {', '.join(sorted(unknown))}")
                    return 2
                raw_key = "vk_" + secrets.token_urlsafe(32)
                expires = (
                    datetime.now(UTC) + timedelta(days=args.days) if args.days else None
                )
                record = await repo.create(
                    tenant_id=args.tenant,
                    user_id=args.user,
                    key_hash=hash_api_key(raw_key),
                    roles=",".join(sorted(roles)) or "member",
                    label=args.label,
                    expires_at=expires,
                )
                await session.commit()
                print(f"key id : {record.id}")
                print(
                    f"tenant : {record.tenant_id}   "
                    f"user: {record.user_id}   roles: {record.roles}"
                )
                print(f"API key: {raw_key}")
                print("Store this key now. It cannot be shown again.")
                return 0

            if args.command == "list-keys":
                for item in await repo.list_keys(tenant_id=args.tenant):
                    state = "REVOKED" if item.revoked_at else "active"
                    print(
                        f"{item.id}  {item.tenant_id}/{item.user_id}  "
                        f"[{item.roles}]  {state}  {item.label or ''}"
                    )
                return 0

            revoked = await repo.revoke(args.key_id)
            await session.commit()
            print("revoked" if revoked else "key not found")
            return 0 if revoked else 1
    finally:
        await engine.dispose()


def main() -> None:
    args = _build_parser().parse_args()
    sync_code = _run_sync(args)
    if sync_code is not None:
        raise SystemExit(sync_code)
    raise SystemExit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
