import aiohttp
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

BASE_URL = "https://api.fluxer.app/v1"


class FluxerTimeout:
    def __init__(self, token: str):
        self.token = token
        self.headers = {
            "Authorization": f"Bot {token}",
            "Content-Type": "application/json"
        }

    async def timeout_member(
        self,
        guild_id: str,
        user_id: str,
        duration_seconds: int,
        reason: str | None = None
    ):
        """
        Timeout a member in a guild.

        Args:
            guild_id: Guild ID
            user_id: User ID
            duration_seconds: Length of timeout
            reason: Optional moderation reason
        """

        timeout_until = (
            datetime.now(timezone.utc) +
            timedelta(seconds=duration_seconds)
        ).isoformat(timespec="milliseconds").replace("+00:00", "Z")

        payload = {
            "communication_disabled_until": timeout_until
        }

        url = f"{BASE_URL}/guilds/{guild_id}/members/{user_id}"
        headers = dict(self.headers)
        if reason:
            headers["X-Audit-Log-Reason"] = quote(reason, safe="")

        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.patch(url, json=payload, headers=headers) as resp:
                if resp.status not in (200, 204):
                    data = await resp.text()
                    raise Exception(f"Timeout failed ({resp.status}): {data}")

                return True