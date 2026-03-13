import aiohttp
import asyncio

BASE_URL = "https://api.fluxer.app/v1"

class InviteLockdown:
    def __init__(self, token: str):
        self.headers = {
            "Authorization": f"Bot {token}",
            "Content-Type": "application/json"
        }

    async def _request(self, method: str, url: str, **kwargs):
        async with aiohttp.ClientSession() as session:
            async with session.request(method, url, headers=self.headers, **kwargs) as r:
                if r.status not in (200, 201, 204):
                    text = await r.text()
                    raise Exception(f"Fluxer API error {r.status}: {text}")
                if r.status != 204:
                    return await r.json()

    async def delete_all_invites(self, guild_id: str):
        """Delete every invite in a guild."""

        invites = await self._request(
            "GET",
            f"{BASE_URL}/guilds/{guild_id}/invites"
        )

        if not isinstance(invites, list):
            return

        for invite in invites:
            await self._request(
                "DELETE",
                f"{BASE_URL}/invites/{invite['code']}"
            )

    async def disable_invite_creation(self, guild_id: str):
        """Remove Create Invite permission from @everyone."""

        payload = {
            "permissions": "0"
        }

        await self._request(
            "PATCH",
            f"{BASE_URL}/guilds/{guild_id}/roles/{guild_id}",
            json=payload
        )

    async def enable_invite_creation(self, guild_id: str, permissions: str):
        """Restore permissions to @everyone."""

        payload = {
            "permissions": permissions
        }

        await self._request(
            "PATCH",
            f"{BASE_URL}/guilds/{guild_id}/roles/{guild_id}",
            json=payload
        )

    async def invite_lockdown(self, guild_id: str, duration: int, original_perms: str):
        """
        Full invite lockdown system.

        duration = seconds
        original_perms = saved permissions for @everyone
        """

        await self.delete_all_invites(guild_id)
        await self.disable_invite_creation(guild_id)

        await asyncio.sleep(duration)

        await self.enable_invite_creation(guild_id, original_perms)