import time
import os
from collections import defaultdict, deque
from typing import Any

import fluxer
from fluxer import Cog

from utils.delete_after import delete_after
from utils.datawrapper import DataWrapper
from utils.embed_builder import EmbedBuilder
from utils.log import log
from utils.timeout import FluxerTimeout


class AntiSpamCog(Cog):
    _LEGACY_TOP_LEVEL_KEYS = {
        "anti_spam_enabled",
        "anti_spam_max_messages",
        "anti_spam_window_seconds",
        "anti_spam_alert_cooldown",
        "anti_spam_timeout_enabled",
        "anti_spam_timeout_duration",
        "anti_spam_log_channel_id",
        "anti_spam_log_channel",
        "anti_spam_staff_role_ids",
        "anti_spam_staff_roles",
        "antispam_log_channel",
        "antispam_staff_roles",
    }

    _LEGACY_NESTED_KEYS = {
        "antispam_enabled",
        "anti_spam_enabled",
        "antispam_max_messages",
        "anti_spam_max_messages",
        "antispam_window_seconds",
        "anti_spam_window_seconds",
        "antispam_alert_cooldown",
        "anti_spam_alert_cooldown",
        "antispam_timeout_enabled",
        "anti_spam_timeout_enabled",
        "antispam_timeout_duration",
        "anti_spam_timeout_duration",
        "antispam_log_channel_id",
        "anti_spam_log_channel_id",
        "antispam_log_channel",
        "anti_spam_log_channel",
        "antispam_staff_role_ids",
        "anti_spam_staff_role_ids",
        "antispam_staff_roles",
        "anti_spam_staff_roles",
    }

    def __init__(self, bot: fluxer.Bot):
        super().__init__(bot)
        self.bot = bot
        self.datawrapper = DataWrapper()
        self.user_windows: dict[tuple[int, int], deque[float]] = defaultdict(deque)
        self.last_alert_at: dict[tuple[int, int], float] = {}

    @staticmethod
    def _resolve_from_payload(payload: Any, *keys: str) -> Any:
        if not isinstance(payload, dict):
            return None

        for key in keys:
            if key in payload:
                return payload.get(key)

        for value in payload.values():
            if isinstance(value, dict):
                nested = AntiSpamCog._resolve_from_payload(value, *keys)
                if nested is not None:
                    return nested

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

    async def _resolve_alert_channel(self, guild: fluxer.Guild, channel_id: str | None, fallback=None):
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

            if channel is None:
                guild_get_channel = getattr(guild, "get_channel", None)
                if callable(guild_get_channel):
                    if numeric_id is not None:
                        channel = guild_get_channel(numeric_id)
                    if channel is None:
                        channel = guild_get_channel(normalized_id)

            if channel is None:
                try:
                    if numeric_id is not None:
                        channel = await self.bot.fetch_channel(numeric_id)
                    else:
                        channel = await self.bot.fetch_channel(normalized_id)
                except Exception:
                    channel = None

            if channel is not None:
                return channel

            log(f"Configured anti-spam log channel could not be resolved: {channel_id}", "warn")

        return fallback

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
        config = await self.datawrapper.get_guild_config(guild_id) or {}
        nested_automod = config.get("automod_settings") if isinstance(config.get("automod_settings"), dict) else {}

        compact = {}
        for candidate in (
            config.get("antispam"),
            nested_automod.get("antispam"),
            config.get("anti_spam"),
            nested_automod.get("anti_spam"),
        ):
            if isinstance(candidate, dict):
                compact = candidate
                break

        return {
            "enabled": self._bool_like(
                (compact.get("enabled") if compact else None)
                if compact
                else self._resolve_from_payload(config, "antispam_enabled", "anti_spam_enabled"),
                True,
            ),
            "max_messages": max(
                1,
                self._int_like(
                    (compact.get("max_messages") if compact else None)
                    if compact
                    else self._resolve_from_payload(config, "antispam_max_messages", "anti_spam_max_messages"),
                    5,
                ),
            ),
            "window_seconds": max(
                1,
                self._int_like(
                    (compact.get("window_seconds") if compact else None)
                    if compact
                    else self._resolve_from_payload(config, "antispam_window_seconds", "anti_spam_window_seconds"),
                    3,
                ),
            ),
            "alert_cooldown": max(
                1,
                self._int_like(
                    (compact.get("alert_cooldown") if compact else None)
                    if compact
                    else self._resolve_from_payload(config, "antispam_alert_cooldown", "anti_spam_alert_cooldown"),
                    10,
                ),
            ),
            "timeout_enabled": self._bool_like(
                (compact.get("timeout_enabled") if compact else None)
                if compact
                else self._resolve_from_payload(
                    config,
                    "antispam_timeout_enabled",
                    "anti_spam_timeout_enabled",
                ),
                True,
            ),
            "timeout_duration": max(
                5,
                self._int_like(
                    (compact.get("timeout_duration") if compact else None)
                    if compact
                    else self._resolve_from_payload(
                        config,
                        "antispam_timeout_duration",
                        "anti_spam_timeout_duration",
                    ),
                    30,
                ),
            ),
            "log_channel_id": str(
                (compact.get("log_channel_id") if compact else None)
                if compact
                else self._resolve_from_payload(
                    config,
                    "antispam_log_channel_id",
                    "anti_spam_log_channel_id",
                    "antispam_log_channel",
                    "anti_spam_log_channel",
                    "automod_log_channel",
                )
                or ""
            ).strip(),
            "staff_role_ids": self._role_ids(
                (compact.get("staff_role_ids") if compact else None)
                if compact
                else self._resolve_from_payload(
                    config,
                    "antispam_staff_role_ids",
                    "anti_spam_staff_role_ids",
                    "antispam_staff_roles",
                    "anti_spam_staff_roles",
                )
            ),
        }

    async def _save_settings(self, guild_id: int, settings: dict[str, Any]) -> None:
        config = await self.datawrapper.get_guild_config(guild_id) or {}
        compact = {
            "enabled": bool(settings.get("enabled", True)),
            "max_messages": int(settings.get("max_messages", 5)),
            "window_seconds": int(settings.get("window_seconds", 3)),
            "alert_cooldown": int(settings.get("alert_cooldown", 10)),
            "timeout_enabled": bool(settings.get("timeout_enabled", True)),
            "timeout_duration": int(settings.get("timeout_duration", 30)),
            "log_channel_id": str(settings.get("log_channel_id", "") or "").strip(),
            "staff_role_ids": self._role_ids(settings.get("staff_role_ids")),
        }

        for legacy_key in self._LEGACY_TOP_LEVEL_KEYS:
            config.pop(legacy_key, None)

        config["antispam_enabled"] = compact["enabled"]
        config["antispam_max_messages"] = compact["max_messages"]
        config["antispam_window_seconds"] = compact["window_seconds"]
        config["antispam_alert_cooldown"] = compact["alert_cooldown"]
        config["antispam_timeout_enabled"] = compact["timeout_enabled"]
        config["antispam_timeout_duration"] = compact["timeout_duration"]
        config["antispam_log_channel_id"] = compact["log_channel_id"]
        config["antispam_staff_role_ids"] = compact["staff_role_ids"]
        config["antispam"] = compact

        nested_automod = config.get("automod_settings")
        if not isinstance(nested_automod, dict):
            nested_automod = {}

        for legacy_key in self._LEGACY_NESTED_KEYS:
            nested_automod.pop(legacy_key, None)

        nested_automod["antispam"] = dict(compact)
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


    @Cog.listener()
    async def on_message(self, message: fluxer.Message):
        if getattr(getattr(message, "author", None), "bot", False):
            return

        guild = getattr(message, "guild", None)
        if guild is None:
            return

        guild_id = getattr(guild, "id", None)
        author_id = getattr(getattr(message, "author", None), "id", None)
        if guild_id is None or author_id is None:
            return

        settings = await self._get_settings(guild_id)
        if not settings.get("enabled", True):
            return

        now = time.monotonic()
        key = (guild_id, author_id)
        window = self.user_windows[key]
        window_seconds = int(settings["window_seconds"])

        while window and (now - window[0]) > window_seconds:
            window.popleft()

        window.append(now)

        max_messages = int(settings["max_messages"])
        if len(window) < max_messages:
            return

        last_alert = self.last_alert_at.get(key, 0.0)
        if (now - last_alert) < int(settings.get("alert_cooldown", 10)):
            return

        self.last_alert_at[key] = now

        try:
            await message.delete()
        except Exception:
            pass

        alert_channel: Any = await self._resolve_alert_channel(
            guild,
            settings.get("log_channel_id"),
            fallback=getattr(message, "channel", None),
        )
        if alert_channel is None:
            return
        
        warning_channel = getattr(message, "channel", None)

        mention_content = " ".join([f"<@&{role_id}>" for role_id in settings.get("staff_role_ids", [])])

        warning_text = (
            f"{message.author.mention} please slow down. "
            f"Triggered anti-spam (`{max_messages}` messages / `{window_seconds}`s)."
        )

        alert_text = EmbedBuilder().create_embed(
            title="Anti-Spam Alert",
            description=f"User {message.author} (`{author_id}`) triggered anti-spam in {message.channel.mention}.\n"
            f"- Messages in window: `{len(window)}`\n"
            f"- Timeframe: `{window_seconds}` seconds\n"
            f"- Message content: {message.content[:200] + ('...' if len(message.content) > 200 else '')}\n"
        )

        if settings.get("timeout_enabled", True):
            timeout_duration = int(settings.get("timeout_duration", 30))
            token = self._resolve_bot_token()
            if not token:
                log("Anti-spam timeout skipped: unable to resolve bot token.", "error")
            else:
                timeout = FluxerTimeout(token)
                try:
                    await timeout.timeout_member(
                        guild_id=str(guild_id),
                        user_id=str(author_id),
                        duration_seconds=timeout_duration,
                        reason="Triggered anti-spam protection",
                    )
                    log(
                        f"Applied anti-spam timeout to user {author_id} in guild {guild_id} for {timeout_duration}s.",
                        "info",
                    )
                except Exception as exc:
                    log(
                        f"Failed anti-spam timeout for user {author_id} in guild {guild_id}: {exc}",
                        "error",
                    )

        await alert_channel.send(embed=alert_text)
        warning = await warning_channel.send(f"{mention_content} {warning_text}".strip())
        await delete_after(warning, 6)

        

async def setup(bot: fluxer.Bot):
    await bot.add_cog(AntiSpamCog(bot))
