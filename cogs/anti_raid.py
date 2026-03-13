import time
import os
from collections.abc import Awaitable
from collections import defaultdict, deque
from typing import Any

import fluxer
from fluxer import Cog

from utils.delete_after import delete_after
from utils.datawrapper import DataWrapper
from utils.log import log
from utils.timeout import FluxerTimeout
from utils.embed_builder import EmbedBuilder

class AntiRaidCog(Cog):
    _LEGACY_TOP_LEVEL_KEYS = {
        "anti_raid_enabled",
        "anti_raid_join_threshold",
        "anti_raid_window_seconds",
        "anti_raid_alert_cooldown",
        "anti_raid_timeout_enabled",
        "anti_raid_timeout_duration",
        "anti_raid_log_channel_id",
        "anti_raid_log_channel",
        "anti_raid_staff_role_ids",
        "anti_raid_staff_roles",
        "antiraid_log_channel",
        "antiraid_staff_roles",
    }

    _LEGACY_NESTED_KEYS = {
        "antiraid_enabled",
        "anti_raid_enabled",
        "antiraid_join_threshold",
        "anti_raid_join_threshold",
        "antiraid_window_seconds",
        "anti_raid_window_seconds",
        "antiraid_alert_cooldown",
        "anti_raid_alert_cooldown",
        "antiraid_timeout_enabled",
        "anti_raid_timeout_enabled",
        "antiraid_timeout_duration",
        "anti_raid_timeout_duration",
        "antiraid_log_channel_id",
        "anti_raid_log_channel_id",
        "antiraid_log_channel",
        "anti_raid_log_channel",
        "antiraid_staff_role_ids",
        "anti_raid_staff_role_ids",
        "antiraid_staff_roles",
        "anti_raid_staff_roles",
    }

    def __init__(self, bot: fluxer.Bot):
        super().__init__(bot)
        self.bot = bot
        self.datawrapper = DataWrapper()
        self.join_windows: dict[int, deque[float]] = defaultdict(deque)
        self.last_alert_at: dict[int, float] = {}

    @staticmethod
    def _resolve_from_payload(payload: Any, *keys: str) -> Any:
        if not isinstance(payload, dict):
            return None

        for key in keys:
            if key in payload:
                return payload.get(key)

        for value in payload.values():
            if isinstance(value, dict):
                nested = AntiRaidCog._resolve_from_payload(value, *keys)
                if nested is not None:
                    return nested

        return None

    @staticmethod
    def _is_empty_value(value: Any) -> bool:
        if value is None:
            return True
        if isinstance(value, str):
            return not value.strip()
        if isinstance(value, (list, tuple, set, dict)):
            return len(value) == 0
        return False

    @classmethod
    def _resolve_first_nonempty(cls, payload: Any, *keys: str) -> Any:
        for key in keys:
            value = cls._resolve_from_payload(payload, key)
            if not cls._is_empty_value(value):
                return value
        return None

    @staticmethod
    def _bool_like(value: Any, default: bool) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"true", "1", "yes", "on"}:
                return True
            if lowered in {"false", "0", "no", "off"}:
                return False
        return default

    @staticmethod
    def _int_like(value: Any, default: int) -> int:
        try:
            if isinstance(value, str):
                return int(value.strip())
            return int(value)
        except Exception:
            return default

    @staticmethod
    def _role_ids(value: Any) -> list[str]:
        if value is None:
            return []

        parts: list[str] = []
        if isinstance(value, list):
            parts = [str(item).strip() for item in value]
        elif isinstance(value, str):
            parts = [segment.strip() for segment in value.split(",")]
        else:
            parts = [str(value).strip()]

        cleaned: list[str] = []
        for part in parts:
            if not part or part in cleaned:
                continue
            cleaned.append(part)
            if len(cleaned) >= 5:
                break

        return cleaned

    async def _resolve_alert_channel(self, guild: fluxer.Guild | None, channel_id: str | None, fallback=None):
        if channel_id:
            channel = None
            normalized_id = str(channel_id).strip()
            numeric_id = int(normalized_id) if normalized_id.isdigit() else None

            get_channel = getattr(self.bot, "get_channel", None)
            if callable(get_channel):
                if numeric_id is not None:
                    channel = get_channel(numeric_id)
                if channel is None:
                    channel = get_channel(normalized_id)

            if channel is None and guild is not None:
                guild_get_channel = getattr(guild, "get_channel", None)
                if callable(guild_get_channel):
                    if numeric_id is not None:
                        channel = guild_get_channel(numeric_id)
                    if channel is None:
                        channel = guild_get_channel(normalized_id)

            if channel is None:
                try:
                    channel = await self.bot.fetch_channel(normalized_id)
                except Exception:
                    channel = None

            if channel is not None:
                return channel

            log(f"Configured anti-raid log channel could not be resolved: {channel_id}", "warn")

        return fallback

    async def _resolve_guild(self, guild_id: int):
        guild: Any = None
        get_guild = getattr(self.bot, "get_guild", None)
        if callable(get_guild):
            guild = get_guild(guild_id)
            if guild is None:
                guild = get_guild(str(guild_id))

        if guild is None:
            fetch_guild = getattr(self.bot, "fetch_guild", None)
            if callable(fetch_guild):
                try:
                    result = fetch_guild(str(guild_id))
                    if isinstance(result, Awaitable):
                        guild = await result
                    else:
                        guild = result
                except Exception:
                    guild = None

        return guild

    def _resolve_bot_token(self) -> str | None:
        candidates = [
            getattr(self.bot, "token", None),
            getattr(self.bot, "_token", None),
            getattr(self.bot, "access_token", None),
            getattr(getattr(self.bot, "http", None), "token", None),
            getattr(getattr(self.bot, "http", None), "_token", None),
            os.getenv("TOKEN"),
        ]

        for candidate in candidates:
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
        return None

    async def _get_settings(self, guild_id: int) -> dict[str, Any]:
        raw_config = await self.datawrapper.get_guild_config(guild_id) or {}
        config: dict[str, Any] = raw_config if isinstance(raw_config, dict) else {}
        nested_value = config.get("automod_settings")
        nested_automod: dict[str, Any] = nested_value if isinstance(nested_value, dict) else {}

        compact: dict[str, Any] = {}
        for candidate in (
            config.get("antiraid"),
            nested_automod.get("antiraid"),
            config.get("anti_raid"),
            nested_automod.get("anti_raid"),
        ):
            if isinstance(candidate, dict):
                compact = candidate
                break

        def pick(compact_key: str, *legacy_keys: str):
            compact_value = self._resolve_first_nonempty(compact, compact_key) if compact else None
            if not self._is_empty_value(compact_value):
                return compact_value
            return self._resolve_first_nonempty(config, *legacy_keys)

        return {
            "enabled": self._bool_like(
                pick("enabled", "antiraid_enabled", "anti_raid_enabled"),
                True,
            ),
            "join_threshold": max(
                1,
                self._int_like(
                    pick("join_threshold", "antiraid_join_threshold", "anti_raid_join_threshold"),
                    8,
                ),
            ),
            "window_seconds": max(
                1,
                self._int_like(
                    pick("window_seconds", "antiraid_window_seconds", "anti_raid_window_seconds"),
                    12,
                ),
            ),
            "alert_cooldown": max(
                1,
                self._int_like(
                    pick("alert_cooldown", "antiraid_alert_cooldown", "anti_raid_alert_cooldown"),
                    30,
                ),
            ),
            "timeout_enabled": self._bool_like(
                pick(
                    "timeout_enabled",
                    "antiraid_timeout_enabled",
                    "anti_raid_timeout_enabled",
                ),
                True,
            ),
            "timeout_duration": max(
                5,
                self._int_like(
                    pick(
                        "timeout_duration",
                        "antiraid_timeout_duration",
                        "anti_raid_timeout_duration",
                    ),
                    30,
                ),
            ),
            "log_channel_id": str(
                pick(
                    "log_channel_id",
                    "antiraid_log_channel_id",
                    "anti_raid_log_channel_id",
                    "antiraid_log_channel",
                    "anti_raid_log_channel",
                    "automod_log_channel_id",
                    "automod_log_channel",
                    "log_channel_id",
                    "log_channel",
                )
                or ""
            ).strip(),
            "staff_role_ids": self._role_ids(
                pick(
                    "staff_role_ids",
                    "antiraid_staff_role_ids",
                    "anti_raid_staff_role_ids",
                    "antiraid_staff_roles",
                    "anti_raid_staff_roles",
                    "staff_role_ids",
                    "staff_roles",
                    "automod_ping_role_ids",
                    "staff_ping_role_ids",
                )
            ),
        }

    async def _save_settings(self, guild_id: int, settings: dict[str, Any]) -> None:
        config = await self.datawrapper.get_guild_config(guild_id) or {}
        compact = {
            "enabled": bool(settings.get("enabled", True)),
            "join_threshold": int(settings.get("join_threshold", 8)),
            "window_seconds": int(settings.get("window_seconds", 12)),
            "alert_cooldown": int(settings.get("alert_cooldown", 30)),
            "timeout_enabled": bool(settings.get("timeout_enabled", True)),
            "timeout_duration": int(settings.get("timeout_duration", 30)),
            "log_channel_id": str(settings.get("log_channel_id", "") or "").strip(),
            "staff_role_ids": self._role_ids(settings.get("staff_role_ids")),
        }

        for legacy_key in self._LEGACY_TOP_LEVEL_KEYS:
            config.pop(legacy_key, None)

        config["antiraid_enabled"] = compact["enabled"]
        config["antiraid_join_threshold"] = compact["join_threshold"]
        config["antiraid_window_seconds"] = compact["window_seconds"]
        config["antiraid_alert_cooldown"] = compact["alert_cooldown"]
        config["antiraid_timeout_enabled"] = compact["timeout_enabled"]
        config["antiraid_timeout_duration"] = compact["timeout_duration"]
        config["antiraid_log_channel_id"] = compact["log_channel_id"]
        config["antiraid_staff_role_ids"] = compact["staff_role_ids"]
        config["antiraid"] = compact

        nested_automod = config.get("automod_settings")
        if not isinstance(nested_automod, dict):
            nested_automod = {}

        for legacy_key in self._LEGACY_NESTED_KEYS:
            nested_automod.pop(legacy_key, None)

        nested_automod["antiraid"] = dict(compact)
        config["automod_settings"] = nested_automod

        await self.datawrapper.set_guild_config(guild_id, config)

    def _permission_value(self, permission: Any) -> int:
        raw_value = getattr(permission, "value", permission)
        try:
            return int(raw_value)
        except Exception:
            return 0

    def _has_manage_guild(self, ctx: fluxer.Message) -> bool:
        author = getattr(ctx, "author", None)
        if author is None:
            return False

        perms = getattr(author, "permissions", None)
        if perms is None:
            return True

        user_perms = self._permission_value(perms)
        needed = self._permission_value(fluxer.Permissions.MANAGE_GUILD)
        if needed <= 0:
            return True
        return (user_perms & needed) == needed

    async def _require_manage_guild(self, ctx: fluxer.Message) -> bool:
        if self._has_manage_guild(ctx):
            return True

        warning = await ctx.reply("You need `MANAGE_GUILD` to use this command.")
        await delete_after(warning, 10)
        return False

    async def _handle_member_join_event(self, member):
        guild = getattr(member, "guild", None)
        guild_id = getattr(guild, "id", None)
        member_id = getattr(getattr(member, "user", None), "id", None) or getattr(member, "id", None)

        if isinstance(member, dict):
            raw_guild_id = member.get("guild_id")
            raw_user_value = member.get("user")
            raw_user: dict[str, Any] = raw_user_value if isinstance(raw_user_value, dict) else {}
            raw_user_id = raw_user.get("id") or member.get("user_id")

            try:
                guild_id = int(raw_guild_id) if raw_guild_id is not None else guild_id
            except Exception:
                guild_id = guild_id

            try:
                member_id = int(raw_user_id) if raw_user_id is not None else member_id
            except Exception:
                member_id = member_id

            if guild is None and guild_id is not None:
                guild = await self._resolve_guild(guild_id)

        if guild_id is None:
            log("Anti-raid join payload missing guild id; skipping.", "warn")
            return

        log(f"Anti-raid observed member join in guild {guild_id} (member: {member_id}).", "info")

        settings = await self._get_settings(guild_id)
        if not settings.get("enabled", True):
            log(f"Anti-raid disabled in guild {guild_id}; skipping join check.", "info")
            return

        now = time.monotonic()
        window = self.join_windows[guild_id]
        window_seconds = int(settings["window_seconds"])

        while window and (now - window[0]) > window_seconds:
            window.popleft()

        window.append(now)

        join_threshold = int(settings["join_threshold"])
        if len(window) < join_threshold:
            return

        last_alert = self.last_alert_at.get(guild_id, 0.0)
        if (now - last_alert) < int(settings.get("alert_cooldown", 30)):
            return

        self.last_alert_at[guild_id] = now

        channel: Any = await self._resolve_alert_channel(
            guild,
            settings.get("log_channel_id"),
            fallback=getattr(guild, "system_channel", None) if guild is not None else None,
        )
        if channel is None:
            log(
                f"Anti-raid trigger in guild {guild_id}, but no alert channel is configured/resolvable.",
                "warn",
            )
            return

        mention_content = " ".join([f"<@&{role_id}>" for role_id in settings.get("staff_role_ids", [])])
        member_mention = getattr(member, "mention", None) or f"<@{member_id}>"

        if settings.get("timeout_enabled", True) and member_id is not None:
            timeout_duration = int(settings.get("timeout_duration", 30))
            token = self._resolve_bot_token()
            if not token:
                log("Anti-raid timeout skipped: unable to resolve bot token.", "error")
            else:
                timeout = FluxerTimeout(token)
                try:
                    await timeout.timeout_member(
                        guild_id=str(guild_id),
                        user_id=str(member_id),
                        duration_seconds=timeout_duration,
                        reason="Triggered anti-raid protection",
                    )
                    log(
                        f"Applied anti-raid timeout to user {member_id} in guild {guild_id} for {timeout_duration}s.",
                        "info",
                    )
                except Exception as exc:
                    log(
                        f"Failed anti-raid timeout for user {member_id} in guild {guild_id}: {exc}",
                        "error",
                    )


        alert = EmbedBuilder().create_embed(
            title="Potential Raid Detected",
            description=(
                f"**Joins in the last `{window_seconds}` seconds:** `{len(window)}`\n"
                f"**Latest join:** {member_mention}\n"
                f"**Action taken:** {'Timeout applied' if settings.get('timeout_enabled', True) else 'No timeout'}"
            ),
            color=0xFF0000
        )

        await channel.send(
            f"{mention_content}",
            embed=alert
        )

    @Cog.listener()
    async def on_member_join(self, member):
        await self._handle_member_join_event(member)

    @Cog.listener()
    async def on_guild_member_add(self, member):
        await self._handle_member_join_event(member)

async def setup(bot: fluxer.Bot):
    await bot.add_cog(AntiRaidCog(bot))
