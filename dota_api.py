import os
import aiohttp
import asyncio
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class DotaAPI:
    # OpenDota item IDs for Aghanim's Scepter and Shard.
    # These items' real effects are hero-dependent and must be resolved
    # against /constants/aghs_desc using the carry's hero_id.
    AGHS_SCEPTER_ITEM_ID = 108
    AGHS_SHARD_ITEM_ID = 609

    def __init__(self):
        self.hero_map = {}
        self.item_map = {}
        # Per-hero Aghs/Shard data, keyed by hero_id (int).
        # Each value is a dict with keys: has_scepter, scepter_desc, scepter_skill_name,
        # has_shard, shard_desc, shard_skill_name.
        self.aghs_map = {}
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

                # Fetch items. Store the live effect-bearing fields so we can
                # ground the LLM in current patch text instead of its training memory.
                async with session.get(f"{self.base_url}/constants/items") as resp:
                    if resp.status == 200:
                        items = await resp.json()
                        self.item_map = {}
                        for key, value in items.items():
                            if "id" in value and "dname" in value:
                                self.item_map[str(value["id"])] = {
                                    "dname": value["dname"],
                                    # abilities[].description is the gold: current
                                    # active/passive effect text with numbers inlined.
                                    "abilities": value.get("abilities") or [],
                                    # attrib[].display contains stat lines like
                                    # "+ {value} Strength" — current patch numbers.
                                    "attrib": value.get("attrib") or [],
                                }
                    else:
                        logger.error(f"Failed to fetch items: {resp.status}")

                # Fetch per-hero Aghanim's Scepter / Shard effects.
                # The base Aghs/Shard items only carry generic stats — the actual
                # gameplay effect is defined per hero here.
                async with session.get(f"{self.base_url}/constants/aghs_desc") as resp:
                    if resp.status == 200:
                        aghs_list = await resp.json()
                        self.aghs_map = {entry["hero_id"]: entry for entry in aghs_list if "hero_id" in entry}
                    else:
                        logger.error(f"Failed to fetch aghs_desc: {resp.status}")

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

    def _format_item_effect(self, item_id: int, hero_id: int) -> str:
        """
        Build a one-line effect description for an item using live OpenDota
        constants data. The LLM uses this to ground its 'why' reasoning in
        current patch behavior instead of stale training memory.

        For Aghanim's Scepter and Shard the effect is hero-dependent, so we
        look it up in self.aghs_map keyed by hero_id.
        """
        # Hero-specific override for Aghs Scepter / Shard.
        if item_id in (self.AGHS_SCEPTER_ITEM_ID, self.AGHS_SHARD_ITEM_ID):
            aghs_entry = self.aghs_map.get(hero_id)
            if aghs_entry:
                if item_id == self.AGHS_SCEPTER_ITEM_ID and aghs_entry.get("has_scepter"):
                    name = aghs_entry.get("scepter_skill_name") or "Aghs Upgrade"
                    desc = (aghs_entry.get("scepter_desc") or "").strip()
                    if desc:
                        return f"AGHS ({name}): {desc}"
                if item_id == self.AGHS_SHARD_ITEM_ID and aghs_entry.get("has_shard"):
                    name = aghs_entry.get("shard_skill_name") or "Shard Upgrade"
                    desc = (aghs_entry.get("shard_desc") or "").strip()
                    if desc:
                        return f"SHARD ({name}): {desc}"
            # If no per-hero data, fall through to the generic item text.

        info = self.item_map.get(str(item_id))
        if not info:
            return ""

        parts = []

        # Active/passive abilities — the most patch-volatile piece. Skip the
        # generic "Ability Upgrade" placeholders that Aghs/Shard carry.
        for ab in info.get("abilities", []):
            title = (ab.get("title") or "").strip()
            description = (ab.get("description") or "").strip()
            if not description or title == "Ability Upgrade":
                continue
            kind = (ab.get("type") or "").upper()  # ACTIVE / PASSIVE / TOGGLE
            # Collapse multi-line descriptions into one line for prompt density.
            description = " ".join(description.split())
            prefix = f"{kind} {title}".strip()
            parts.append(f"{prefix}: {description}" if prefix else description)

        # Stat lines from attrib[].display (only entries with a display template).
        stat_lines = []
        for a in info.get("attrib", []):
            display = a.get("display")
            value = a.get("value")
            if not display or value is None:
                continue
            stat_lines.append(str(display).replace("{value}", str(value)).strip())
        if stat_lines:
            parts.append("Stats: " + ", ".join(stat_lines))

        return " | ".join(parts)

    async def get_meta_items(self, hero_name: str) -> str:
        if not self._initialized:
            await self.initialize()

        hero_id = self._resolve_hero_id(hero_name)
        if not hero_id:
            logger.warning(f"Could not find hero ID for {hero_name}")
            return ""

        async with aiohttp.ClientSession() as session:
            try:
                # NOTE: OpenDota's path is camelCase `itemPopularity`. The previous
                # snake_case spelling returned 404, which silently disabled the
                # whole live-meta feature and made the bot fall back to the LLM's
                # training memory — the root cause of stale item explanations.
                async with session.get(f"{self.base_url}/heroes/{hero_id}/itemPopularity") as resp:
                    if resp.status != 200:
                        logger.error(f"Failed to fetch item popularity for hero {hero_id}: {resp.status}")
                        return ""

                    data = await resp.json()
                    popular_items = []
                    seen_items = set()

                    for phase, label in [
                        ('start_game_items', 'Starting'),
                        ('early_game_items', 'Early'),
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
                                    effect = self._format_item_effect(int(item_id), hero_id)
                                    if effect:
                                        popular_items.append(f"[{label}] {dname} — {effect}")
                                    else:
                                        popular_items.append(f"[{label}] {dname}")

                    return "\n".join(popular_items) if popular_items else ""
            except Exception as e:
                logger.error(f"Error fetching meta items: {e}")
                return ""

    async def get_matchup_context(self, carry_name: str, enemy_names: list) -> str:
        if not self._initialized:
            await self.initialize()

        stratz_key = os.environ.get("STRATZ_API_KEY", "")
        if not stratz_key:
            logger.warning("STRATZ_API_KEY not set, skipping matchup data")
            return ""

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

        query = """
        query HeroMatchup($heroId: Short!) {
          heroStats {
            matchUp(heroId: $heroId, bracketBasicIds: [HERALD_GUARDIAN, CRUSADER_ARCHON]) {
              vs {
                heroId2
                winsAverage
                matchCount
              }
            }
          }
        }
        """

        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(
                    "https://api.stratz.com/graphql",
                    json={"query": query, "variables": {"heroId": carry_id}},
                    headers={
                        "Authorization": f"Bearer {stratz_key}",
                        "Content-Type": "application/json",
                        "User-Agent": "STRATZ_API",
                    },
                ) as resp:
                    if resp.status != 200:
                        logger.error(f"Stratz API returned {resp.status}")
                        return ""

                    data = await resp.json()
                    matchup_list = (
                        data.get("data", {})
                        .get("heroStats", {})
                        .get("matchUp", [])
                    )
                    vs_list = matchup_list[0].get("vs", []) if matchup_list else []

                    results = []
                    for entry in vs_list:
                        if entry["heroId2"] in enemy_ids:
                            games = entry.get("matchCount", 0)
                            if games < 100:
                                continue
                            wr = round(entry["winsAverage"] * 100, 1)
                            label = "favored" if wr >= 50 else "disadvantage"
                            results.append(
                                f"{carry_name} vs {enemy_ids[entry['heroId2']]}: {wr}% WR over {games:,} games ({label})"
                            )

                    return "\n".join(results) if results else ""
            except Exception as e:
                logger.error(f"Error fetching Stratz matchup data: {e}")
                return ""

# Create a singleton instance to be used across the bot
dota_api = DotaAPI()
