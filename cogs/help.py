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
            "FluxMod Command List",
            f"All commands use the prefix `{prefix}`.",
            Colors.primary,
        )

        embed_help.add_field(
            name="AutoMod Rules (Dashboard)",
            value=(
                "AutoMod rules are managed via the dashboard at [https://fluxmod.app](https://fluxmod.app).\n"
                "Each rule has an **Action** (warn / delete / timeout / kick / ban / no_action), "
                "a configurable **Timeout Duration**, and optional **Offense Escalation** "
                "(1st violation = warn, repeat = timeout)."
            ),
            inline=False,
        )

        embed_help.add_field(
            name="Warning System",
            value=(
                f"`{prefix}warnings <@user|user_id>`\n"
                "View all recorded warnings for a user.\n\n"
                f"`{prefix}delwarn <@user|user_id> <index>`\n"
                "Delete one warning by its index number."
            ),
            inline=False,
        )

        embed_help.add_field(
            name="Configuration (Dashboard)",
            value=(
                "Guild settings — log channels, exempt roles/channels/users, Anti-Spam, Anti-Raid, "
                "and Anti-Nuke thresholds — are all configured from the dashboard."
            ),
            inline=False,
        )

        embed_help.add_field(
            name="Useful Links",
            value=(
                "[Dashboard](https://fluxmod.app)  •  "
                "[Invite Bot](https://web.fluxer.app/oauth2/authorize?client_id=1475487256413421606&scope=bot&permissions=4504699407788166)  •  "
                "[Support Server](https://fluxer.gg/cTPTpEsu)"
            ),
            inline=False,
        )

        embed_help.set_footer(text=f"Prefix: {prefix} | Use mentions or IDs where accepted")
        await ctx.reply(embed=embed_help)

async def setup(bot: fluxer.Bot):
    await bot.add_cog(HelpCog(bot))