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

    async def get_meta_items(self, hero_name: str) -> str:
        if not self._initialized:
            await self.initialize()

        # Handle formatting differences (e.g., Anti-Mage vs Anti Mage)
        hero_id = None
        search_name = hero_name.lower().strip().replace("-", "")
        
        for name, h_id in self.hero_map.items():
            formatted_name = name.replace("-", "")
            if search_name == formatted_name:
                hero_id = h_id
                break
        
        # Fallback to substring matching if exact match fails
        if not hero_id:
            for name, h_id in self.hero_map.items():
                if search_name in name.replace("-", "") or name.replace("-", "") in search_name:
                    hero_id = h_id
                    break

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
                    
                    # Extract top items for mid and late game
                    for phase in ['mid_game_items', 'late_game_items']:
                        phase_items = data.get(phase, {})
                        # Sort items by popularity count (descending)
                        sorted_items = sorted(phase_items.items(), key=lambda x: x[1], reverse=True)
                        
                        # Take top 3 from each phase
                        for item_id, count in sorted_items[:3]:
                            item_info = self.item_map.get(str(item_id))
                            if item_info:
                                dname = item_info["dname"]
                                desc = item_info["desc"]
                                if dname not in seen_items:
                                    seen_items.add(dname)
                                    formatted_item = f"{dname} ({desc})" if desc else dname
                                    popular_items.append(formatted_item)
                    
                    if popular_items:
                        return " | ".join(popular_items)
                    return ""
            except Exception as e:
                logger.error(f"Error fetching meta items: {e}")
                return ""

# Create a singleton instance to be used across the bot
dota_api = DotaAPI()
