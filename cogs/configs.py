import fluxer
import re
from fluxer import Cog
from typing import Any

from utils.resolvers import resolve_channel_id, resolve_user_id
from utils.datawrapper import DataWrapper
from utils.delete_after import delete_after
from utils.embed_builder import EmbedBuilder, Colors


class ConfigsCog(Cog):
    def __init__(self, bot: fluxer.Bot):
        super().__init__(bot)
        self.bot = bot
        self.datawrapper = DataWrapper()

    def _permission_value(self, permission: Any) -> int:
        raw_value = getattr(permission, "value", permission)
        try:
            return int(raw_value)
        except Exception:
            return 0

    def _build_embed(self, title: str, description: str, color: int = Colors.primary):
        embed = EmbedBuilder.build_embed(title, description, color)
        embed.set_footer(text="FluxMod AutoMod Config")
        return embed

    def _has_required_permission(self, ctx, permission: Any) -> bool:
        """
        Local permission check to avoid hard failures from Fluxer's decorator path.
        If permission payload is unavailable in this context, fallback allows command.
        """
        author = getattr(ctx, "author", None)
        if author is None:
            return False

        perms = getattr(author, "permissions", None)
        if perms is None:
            # Fallback for gateway payloads that omit permission bitfields.
            return True

        user_perms = self._permission_value(perms)
        needed = self._permission_value(permission)
        if needed <= 0:
            return True
        return (user_perms & needed) == needed

    async def _ensure_permission_or_reply(self, ctx, permission: Any, label: str) -> bool:
        if self._has_required_permission(ctx, permission):
            return True

        warning_message = await ctx.reply(
            embed=self._build_embed(
                "Missing Permission",
                f"You need `{label}` to use this command.",
                Colors.error,
            )
        )
        await delete_after(warning_message, 10)
        return False

    def _resolve_channel_id(self, channel_str: str) -> str | None:
        resolved = resolve_channel_id(channel_str)
        return str(resolved) if resolved else None
    

    def _resolve_user_id(self, user_str: str) -> str | None:
        resolved = resolve_user_id(user_str)
        return str(resolved) if resolved else None

    def _resolve_role_id(self, role_str: str) -> str | None:
        value = str(role_str).strip()
        if value.startswith("<@&") and value.endswith(">"):
            value = value[3:-1]
        if value.isdigit():
            return value
        return None
    
    def _normalize_pattern_list(self, raw_patterns):
        normalized = []
        for pattern in raw_patterns:
            if not isinstance(pattern, str):
                continue

            # Some preset entries are accidentally saved as "a, b" in one slot.
            for part in pattern.split(","):
                clean = part.strip().lower()
                if clean:
                    normalized.append(clean)

        return normalized
    
    def _compile_wildcard_pattern(self, pattern: str):
        try:
            escaped = re.escape(pattern).replace(r"\*", ".*")
            return re.compile(escaped, re.IGNORECASE)
        except re.error:
            return None

    def _default_automod_rule(self) -> dict:
        return {
            "name": "AutoMod Rule",
            "action": "warn",
            "pattern": "",
            "keywords": [],
            "allowed_patterns": [],
            "threshold": 1,
            "enabled": True,
            "exempt_roles": [],
            "exempt_channels": [],
            "exempt_users": [],
        }

    async def _get_primary_rule(self, guild_id: int) -> dict:
        rules = await self.datawrapper.get_automod_rules(guild_id)
        if rules:
            return dict(rules[0])
        return self._default_automod_rule()

    async def _save_primary_rule(self, guild_id: int, rule: dict):
        rule_name = str(rule.get("name") or rule.get("rule_name") or "AutoMod Rule")
        await self.datawrapper.set_automod_rule(guild_id, rule_name, rule)
        

async def setup(bot: fluxer.Bot):
    await bot.add_cog(ConfigsCog(bot))