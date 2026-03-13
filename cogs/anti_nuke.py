import time
import os
from collections import defaultdict, deque
from typing import Any

import fluxer
from fluxer import Cog

from utils.delete_after import delete_after
from utils.datawrapper import DataWrapper
from utils.log import log
from utils.timeout import FluxerTimeout


class AntiNukeCog(Cog):
    _LEGACY_TOP_LEVEL_KEYS = {
        "anti_nuke_enabled",
        "anti_nuke_action_threshold",
        "anti_nuke_window_seconds",
        "anti_nuke_alert_cooldown",
        "anti_nuke_timeout_enabled",
        "anti_nuke_timeout_duration",
        "anti_nuke_log_channel_id",
        "anti_nuke_log_channel",
        "anti_nuke_staff_role_ids",
        "anti_nuke_staff_roles",
        "antinuke_log_channel",
        "antinuke_staff_roles",
    }

    _LEGACY_NESTED_KEYS = {
        "antinuke_enabled",
        "anti_nuke_enabled",
        "antinuke_action_threshold",
        "anti_nuke_action_threshold",
        "antinuke_window_seconds",
        "anti_nuke_window_seconds",
        "antinuke_alert_cooldown",
        "anti_nuke_alert_cooldown",
        "antinuke_timeout_enabled",
        "anti_nuke_timeout_enabled",
        "antinuke_timeout_duration",
        "anti_nuke_timeout_duration",
        "antinuke_log_channel_id",
        "anti_nuke_log_channel_id",
        "antinuke_log_channel",
        "anti_nuke_log_channel",
        "antinuke_staff_role_ids",
        "anti_nuke_staff_role_ids",
        "antinuke_staff_roles",
        "anti_nuke_staff_roles",
    }

    def __init__(self, bot: fluxer.Bot):
        super().__init__(bot)
        self.bot = bot
        self.datawrapper = DataWrapper()
        self.action_windows: dict[tuple[int, int], deque[float]] = defaultdict(deque)
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
                nested = AntiNukeCog._resolve_from_payload(value, *keys)
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
                    if numeric_id is not None:
                        channel = await self.bot.fetch_channel(numeric_id)
                    else:
                        channel = await self.bot.fetch_channel(normalized_id)
                except Exception:
                    channel = None

            if channel is not None:
                return channel

            log(f"Configured anti-nuke log channel could not be resolved: {channel_id}", "warn")

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
            config.get("antinuke"),
            nested_automod.get("antinuke"),
            config.get("anti_nuke"),
            nested_automod.get("anti_nuke"),
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
                pick("enabled", "antinuke_enabled", "anti_nuke_enabled"),
                True,
            ),
            "action_threshold": max(
                1,
                self._int_like(
                    pick("action_threshold", "antinuke_action_threshold", "anti_nuke_action_threshold"),
                    3,
                ),
            ),
            "window_seconds": max(
                1,
                self._int_like(
                    pick("window_seconds", "antinuke_window_seconds", "anti_nuke_window_seconds"),
                    15,
                ),
            ),
            "alert_cooldown": max(
                1,
                self._int_like(
                    pick("alert_cooldown", "antinuke_alert_cooldown", "anti_nuke_alert_cooldown"),
                    20,
                ),
            ),
            "timeout_enabled": self._bool_like(
                pick("timeout_enabled", "antinuke_timeout_enabled", "anti_nuke_timeout_enabled"),
                True,
            ),
            "timeout_duration": max(
                5,
                self._int_like(
                    pick("timeout_duration", "antinuke_timeout_duration", "anti_nuke_timeout_duration"),
                    30,
                ),
            ),
            "log_channel_id": str(
                pick(
                    "log_channel_id",
                    "antinuke_log_channel_id",
                    "anti_nuke_log_channel_id",
                    "antinuke_log_channel",
                    "anti_nuke_log_channel",
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
                    "antinuke_staff_role_ids",
                    "anti_nuke_staff_role_ids",
                    "antinuke_staff_roles",
                    "anti_nuke_staff_roles",
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
            "action_threshold": int(settings.get("action_threshold", 3)),
            "window_seconds": int(settings.get("window_seconds", 15)),
            "alert_cooldown": int(settings.get("alert_cooldown", 20)),
            "timeout_enabled": bool(settings.get("timeout_enabled", True)),
            "timeout_duration": int(settings.get("timeout_duration", 30)),
            "log_channel_id": str(settings.get("log_channel_id", "") or "").strip(),
            "staff_role_ids": self._role_ids(settings.get("staff_role_ids")),
        }

        for legacy_key in self._LEGACY_TOP_LEVEL_KEYS:
            config.pop(legacy_key, None)

        config["antinuke_enabled"] = compact["enabled"]
        config["antinuke_action_threshold"] = compact["action_threshold"]
        config["antinuke_window_seconds"] = compact["window_seconds"]
        config["antinuke_alert_cooldown"] = compact["alert_cooldown"]
        config["antinuke_timeout_enabled"] = compact["timeout_enabled"]
        config["antinuke_timeout_duration"] = compact["timeout_duration"]
        config["antinuke_log_channel_id"] = compact["log_channel_id"]
        config["antinuke_staff_role_ids"] = compact["staff_role_ids"]
        config["antinuke"] = compact

        nested_automod = config.get("automod_settings")
        if not isinstance(nested_automod, dict):
            nested_automod = {}

        for legacy_key in self._LEGACY_NESTED_KEYS:
            nested_automod.pop(legacy_key, None)

        nested_automod["antinuke"] = dict(compact)
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

    def _looks_sensitive_command(self, content: str, prefix: str) -> bool:
        text = content.strip().lower()
        if not text.startswith(prefix.lower()):
            return False

        body = text[len(prefix):].strip()
        dangerous_words = (
            "ban",
            "kick",
            "role delete",
            "channel delete",
            "nuke",
            "prune",
            "mass",
            "purge",
        )
        return any(word in body for word in dangerous_words)


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

        content = str(getattr(message, "content", "") or "")
        prefix = getattr(getattr(self.bot, "command_prefix", None), "strip", lambda: "fm!")()
        if not isinstance(prefix, str) or not prefix:
            prefix = "fm!"

        if not self._looks_sensitive_command(content, prefix):
            return

        now = time.monotonic()
        key = (guild_id, author_id)
        window = self.action_windows[key]
        window_seconds = int(settings["window_seconds"])

        while window and (now - window[0]) > window_seconds:
            window.popleft()

        window.append(now)

        action_threshold = int(settings["action_threshold"])
        if len(window) < action_threshold:
            return

        last_alert = self.last_alert_at.get(key, 0.0)
        if (now - last_alert) < int(settings.get("alert_cooldown", 20)):
            return

        self.last_alert_at[key] = now

        channel: Any = await self._resolve_alert_channel(
            guild,
            settings.get("log_channel_id"),
            fallback=getattr(message, "channel", None),
        )
        if channel is None:
            log(
                f"Anti-nuke trigger in guild {guild_id}, but no alert channel is configured/resolvable.",
                "warn",
            )
            return

        mention_content = " ".join([f"<@&{role_id}>" for role_id in settings.get("staff_role_ids", [])])


        if settings.get("timeout_enabled", True):
            timeout_duration = int(settings.get("timeout_duration", 30))
            token = self._resolve_bot_token()
            if not token:
                log("Anti-nuke timeout skipped: unable to resolve bot token.", "error")
            else:
                timeout = FluxerTimeout(token)
                try:
                    await timeout.timeout_member(
                        guild_id=str(guild_id),
                        user_id=str(author_id),
                        duration_seconds=timeout_duration,
                        reason="Triggered anti-nuke protection",
                    )
                    log(
                        f"Applied anti-nuke timeout to user {author_id} in guild {guild_id} for {timeout_duration}s.",
                        "info",
                    )
                except Exception as exc:
                    log(
                        f"Failed anti-nuke timeout for user {author_id} in guild {guild_id}: {exc}",
                        "error",
                    )

        await channel.send(
            f"{mention_content} Potential nuke pattern detected: "
            f"{message.author.mention} ran `{len(window)}` sensitive commands "
            f"within `{window_seconds}` seconds."
        )


async def setup(bot: fluxer.Bot):
    await bot.add_cog(AntiNukeCog(bot))
