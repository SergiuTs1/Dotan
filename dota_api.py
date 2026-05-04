import aiohttp
import asyncio
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class DotaAPI:
    def __init__(self):
        self.hero_map = {}
        self.item_map = {}
        self.base_url = "https://api.opendota.com/api"
        self._initialized = False

    async def initialize(self):
        if self._initialized:
            return
            
        async with aiohttp.ClientSession() as session:
            try:
                # Fetch heroes
                async with session.get(f"{self.base_url}/heroes") as resp:
                    if resp.status == 200:
                        heroes = await resp.json()
                        # Map lowercase localized name to ID
                        self.hero_map = {hero["localized_name"].lower(): hero["id"] for hero in heroes}
                    else:
                        logger.error(f"Failed to fetch heroes: {resp.status}")

                # Fetch items to map IDs to Display Names
                async with session.get(f"{self.base_url}/constants/items") as resp:
                    if resp.status == 200:
                        items = await resp.json()
                        self.item_map = {}
                        for key, value in items.items():
                            if "id" in value and "dname" in value:
                                # Safely extract the item description/hint
                                hint = value.get("hint")
                                desc = ""
                                if isinstance(hint, list):
                                    desc = " ".join(str(h) for h in hint)
                                elif isinstance(hint, str):
                                    desc = hint
                                
                                self.item_map[str(value["id"])] = {
                                    "dname": value["dname"],
                                    "desc": desc
                                }
                    else:
                        logger.error(f"Failed to fetch items: {resp.status}")
                
                self._initialized = True
            except Exception as e:
                logger.error(f"Error initializing OpenDota API: {e}")

    def _resolve_hero_id(self, hero_name: str) -> int | None:
        search_name = hero_name.lower().strip().replace("-", "").replace(" ", "")
        for name, h_id in self.hero_map.items():
            if search_name == name.replace("-", "").replace(" ", ""):
                return h_id
        for name, h_id in self.hero_map.items():
            normalized = name.replace("-", "").replace(" ", "")
            if search_name in normalized or normalized in search_name:
                return h_id
        return None

    async def get_meta_items(self, hero_name: str) -> str:
        if not self._initialized:
            await self.initialize()

        hero_id = self._resolve_hero_id(hero_name)
        if not hero_id:
            logger.warning(f"Could not find hero ID for {hero_name}")
            return ""

        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(f"{self.base_url}/heroes/{hero_id}/item_popularity") as resp:
                    if resp.status != 200:
                        logger.error(f"Failed to fetch item popularity for hero {hero_id}")
                        return ""

                    data = await resp.json()
                    popular_items = []
                    seen_items = set()

                    for phase, label in [
                        ('start_game_items', 'Early'),
                        ('mid_game_items', 'Mid'),
                        ('late_game_items', 'Late'),
                    ]:
                        phase_items = data.get(phase, {})
                        sorted_items = sorted(phase_items.items(), key=lambda x: x[1], reverse=True)
                        for item_id, _ in sorted_items[:3]:
                            item_info = self.item_map.get(str(item_id))
                            if item_info:
                                dname = item_info["dname"]
                                if dname not in seen_items:
                                    seen_items.add(dname)
                                    popular_items.append(f"[{label}] {dname}")

                    return " | ".join(popular_items) if popular_items else ""
            except Exception as e:
                logger.error(f"Error fetching meta items: {e}")
                return ""

    async def get_matchup_context(self, carry_name: str, enemy_names: list) -> str:
        if not self._initialized:
            await self.initialize()

        carry_id = self._resolve_hero_id(carry_name)
        if not carry_id:
            logger.warning(f"Could not find hero ID for {carry_name}")
            return ""

        enemy_ids = {}
        for name in enemy_names:
            h_id = self._resolve_hero_id(name)
            if h_id:
                enemy_ids[h_id] = name

        if not enemy_ids:
            return ""

        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(f"{self.base_url}/heroes/{carry_id}/matchups") as resp:
                    if resp.status != 200:
                        logger.error(f"Failed to fetch matchups for hero {carry_id}")
                        return ""

                    matchups = await resp.json()
                    results = []
                    for entry in matchups:
                        if entry["hero_id"] in enemy_ids:
                            games = entry["games_played"]
                            if games == 0:
                                continue
                            wr = round(entry["wins"] / games * 100, 1)
                            label = "favored" if wr >= 50 else "disadvantage"
                            results.append(
                                f"{carry_name} vs {enemy_ids[entry['hero_id']]}: {wr}% WR over {games} games ({label})"
                            )

                    return "\n".join(results) if results else ""
            except Exception as e:
                logger.error(f"Error fetching matchup data: {e}")
                return ""

# Create a singleton instance to be used across the bot
dota_api = DotaAPI()
