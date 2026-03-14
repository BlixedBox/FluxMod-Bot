import fluxer
from fluxer import Cog
from utils.embed_builder import EmbedBuilder, Colors


class HelpCog(Cog):
    def __init__(self, bot: fluxer.Bot):
        super().__init__(bot)
        self.bot = bot

    @Cog.command(name="help")
    async def help(self, ctx: fluxer.Message):
        prefix = getattr(getattr(self.bot, "command_prefix", None), "strip", lambda: "!")()
        if not isinstance(prefix, str) or not prefix:
            prefix = "fm!"

        embed_help = EmbedBuilder.build_embed(
            "FluxMod Command Help",
            "Current commands available in this bot.",
            Colors.primary,
        )

        embed_help.add_field(
            name="AutoMod Configuration",
            value=("For Automod configuration, please visit the dashboard at [https://fluxmod.app](https://fluxmod.app)"),
            inline=False,
        )

        embed_help.add_field(
            name="AutoMod Status",
            value=("For Automod status, please visit the dashboard at [https://fluxmod.app](https://fluxmod.app)"),
            inline=False,
        )

        embed_help.add_field(
            name="Warning System",
            value=(
                f"`{prefix}warnings <@user|user_id>`\n"
                "View warnings for a user.\n\n"
                f"`{prefix}delwarn <@user|user_id> <index>`\n"
                "Delete one warning by index."
            ),
            inline=False,
        )

        embed_help.set_footer(text=f"Prefix: {prefix} | Use mentions or IDs where accepted")
        await ctx.reply(embed=embed_help)

async def setup(bot: fluxer.Bot):
    await bot.add_cog(HelpCog(bot))