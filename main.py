from __future__ import annotations

import asyncio
import re
import time
from typing import Any

import aiohttp
import astrbot.api.message_components as Comp
from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api import AstrBotConfig
from astrbot.api.star import Context, Star
from .sts2.image_utils import configure_cjk_font, ensure_cjk_font
from .sts2.paths import DATA_DIR

from .sts2.image_utils import download_icon, save_png
from .sts2.paths import STS2_IMAGE_CACHE_DIR, STS2_IMAGES_DIR
from .sts2.sts2_client import (
    STS2_ENTITY_TYPES,
    SpireCodexClient,
    normalize_sts2_url,
    strip_sts2_markup,
)
from .sts2.sts2_images import render_sts2_detail, render_sts2_detail_bundle, render_sts2_list, render_sts2_overview
from .sts2.sts2_stats_images import render_sts2_card_power_table, render_sts2_power_table_bundle, render_sts2_winrate

_CMD_TO_TYPE = {
    "卡牌": "cards",
    "遗物": "relics",
    "怪物": "monsters",
    "药水": "potions",
    "事件": "events",
    "能力": "powers",
    "角色": "characters",
}

_CHARACTER_ALIASES = {
    "战士": ("ironclad", "战士"),
    "铁甲战士": ("ironclad", "战士"),
    "铁甲戰士": ("ironclad", "战士"),
    "铁卫士": ("ironclad", "战士"),
    "鐵衛士": ("ironclad", "战士"),
    "铁甲": ("ironclad", "战士"),
    "鐵甲": ("ironclad", "战士"),
    "铁": ("ironclad", "战士"),
    "猎人": ("silent", "猎人"),
    "猎手": ("silent", "猎人"),
    "獵人": ("silent", "猎人"),
    "獵手": ("silent", "猎人"),
    "静默猎手": ("silent", "猎人"),
    "靜默獵手": ("silent", "猎人"),
    "寂静猎手": ("silent", "猎人"),
    "寂靜獵手": ("silent", "猎人"),
    "静默": ("silent", "猎人"),
    "靜默": ("silent", "猎人"),
    "寂静": ("silent", "猎人"),
    "寂靜": ("silent", "猎人"),
    "储君": ("regent", "储君"),
    "儲君": ("regent", "储君"),
    "摄政王": ("regent", "储君"),
    "攝政王": ("regent", "储君"),
    "摄政": ("regent", "储君"),
    "攝政": ("regent", "储君"),
    "王储": ("regent", "储君"),
    "王儲": ("regent", "储君"),
    "皇储": ("regent", "储君"),
    "皇儲": ("regent", "储君"),
    "骨妹": ("necrobinder", "骨妹"),
    "骨女": ("necrobinder", "骨妹"),
    "骨头": ("necrobinder", "骨妹"),
    "亡灵契约师": ("necrobinder", "骨妹"),
    "亡靈契約師": ("necrobinder", "骨妹"),
    "亡灵": ("necrobinder", "骨妹"),
    "亡靈": ("necrobinder", "骨妹"),
    "契约师": ("necrobinder", "骨妹"),
    "契約師": ("necrobinder", "骨妹"),
    "死灵": ("necrobinder", "骨妹"),
    "死靈": ("necrobinder", "骨妹"),
    "鸡煲": ("defect", "鸡煲"),
    "雞煲": ("defect", "鸡煲"),
    "机宝": ("defect", "鸡煲"),
    "機寶": ("defect", "鸡煲"),
    "机器人": ("defect", "鸡煲"),
    "機器人": ("defect", "鸡煲"),
    "故障机器人": ("defect", "鸡煲"),
    "故障機器人": ("defect", "鸡煲"),
    "缺陷": ("defect", "鸡煲"),
    "缺陷机器人": ("defect", "鸡煲"),
    "缺陷機器人": ("defect", "鸡煲"),
    "silent": ("silent", "猎人"),
    "ironclad": ("ironclad", "战士"),
    "regent": ("regent", "储君"),
    "necrobinder": ("necrobinder", "骨妹"),
    "defect": ("defect", "鸡煲"),
    "the silent": ("silent", "猎人"),
    "the ironclad": ("ironclad", "战士"),
    "the regent": ("regent", "储君"),
    "the necrobinder": ("necrobinder", "骨妹"),
    "the defect": ("defect", "鸡煲"),
}
_STS2_CHARACTER_ORDER = [
    ("ironclad", "战士"),
    ("silent", "猎人"),
    ("regent", "储君"),
    ("necrobinder", "骨妹"),
    ("defect", "鸡煲"),
]

_COMMON_POWER_ALIASES = {
    "通用",
    "公共",
    "公共牌",
    "中立",
    "中立牌",
    "通用牌",
    "通用卡",
}
_COLORLESS_POWER_ALIASES = {
    "无色",
    "无色牌",
    "无色卡",
    "colorless",
}
_CURSE_POWER_ALIASES = {
    "诅咒",
    "诅咒牌",
    "诅咒卡",
    "curse",
    "curses",
}
_MULTIPLAYER_POWER_ALIASES = {
    "多人",
    "多人牌",
    "多人卡",
    "联机",
    "联机牌",
    "multi",
    "multiplayer",
}

_RELIC_POWER_ALIASES = {
    "遗物",
    "遗物表",
    "relic",
    "relics",
}
_NEOW_POWER_ALIASES = {
    "涅奥",
    "捏奥",
    "初始",
    "初始遗物",
    "复生之母",
    "neow",
}
_ANCIENT_RELIC_SOURCE_ALIASES = {
    "涅奥": ("neow", "涅奥"),
    "捏奥": ("neow", "涅奥"),
    "涅澳": ("neow", "涅奥"),
    "初始": ("neow", "涅奥"),
    "初始遗物": ("neow", "涅奥"),
    "复生之母": ("neow", "涅奥"),
    "鲸鱼": ("neow", "涅奥"),
    "neow": ("neow", "涅奥"),
    "欧洛巴斯": ("orobas", "欧洛巴斯"),
    "欧洛巴": ("orobas", "欧洛巴斯"),
    "欧巴斯": ("orobas", "欧洛巴斯"),
    "欧洛": ("orobas", "欧洛巴斯"),
    "大眼": ("orobas", "欧洛巴斯"),
    "大眼睛": ("orobas", "欧洛巴斯"),
    "奥罗巴斯": ("orobas", "欧洛巴斯"),
    "活体虹光": ("orobas", "欧洛巴斯"),
    "orobas": ("orobas", "欧洛巴斯"),
    "佩尔": ("pael", "佩尔"),
    "佩儿": ("pael", "佩尔"),
    "融化巨龙": ("pael", "佩尔"),
    "pael": ("pael", "佩尔"),
    "特兹卡塔拉": ("tezcatara", "特兹卡塔拉"),
    "稻草人": ("tezcatara", "特兹卡塔拉"),
    "特兹": ("tezcatara", "特兹卡塔拉"),
    "饲火者": ("tezcatara", "特兹卡塔拉"),
    "南瓜头": ("tezcatara", "特兹卡塔拉"),
    "南瓜": ("tezcatara", "特兹卡塔拉"),
    "tez": ("tezcatara", "特兹卡塔拉"),
    "tezcatara": ("tezcatara", "特兹卡塔拉"),
    "诺奴佩普": ("nonupeipe", "诺奴佩普"),
    "富婆": ("nonupeipe", "诺奴佩普"),
    "机缘的化身": ("nonupeipe", "诺奴佩普"),
    "nonu": ("nonupeipe", "诺奴佩普"),
    "nonupeipe": ("nonupeipe", "诺奴佩普"),
    "坦克斯": ("tanx", "坦克斯"),
    "坦克": ("tanx", "坦克斯"),
    "狮子": ("tanx", "坦克斯"),
    "嵌合兽之王": ("tanx", "坦克斯"),
    "tanx": ("tanx", "坦克斯"),
    "瓦库": ("vakuu", "瓦库"),
    "第一个恶魔": ("vakuu", "瓦库"),
    "vaku": ("vakuu", "瓦库"),
    "vakuu": ("vakuu", "瓦库"),
    "达弗": ("darv", "达弗"),
    "老资历": ("darv", "达弗"),
    "大斧": ("darv", "达弗"),
    "达夫": ("darv", "达弗"),
    "囤积者": ("darv", "达弗"),
    "darv": ("darv", "达弗"),
}

_COMMON_CARD_COLORS = {"colorless", "event", "curse"}
_MULTIPLAYER_CARD_IDS = {"TANK"}
_MULTIPLAYER_CARD_TARGETS = {"AnyAlly", "AllAllies"}
_MULTIPLAYER_CARD_MARKERS = ("盟友", "另一名玩家", "另一位玩家", "其他玩家", "所有玩家")
_STS2_MULTI_QUERY_SPLIT_RE = re.compile(r"[\s,，、;；\n]+")
_STS2_GENERIC_TYPE_PRIORITY = {
    "cards": 0,
    "relics": 1,
    "monsters": 2,
    "events": 3,
    "potions": 4,
    "characters": 5,
    "powers": 9,
}

_ANCIENT_RELIC_SOURCE_BY_ID = {
    relic_id: "neow"
    for relic_id in {
        "ARCANE_SCROLL",
        "BOOMING_CONCH",
        "GOLDEN_PEARL",
        "LEAD_PAPERWEIGHT",
        "LOST_COFFER",
        "NEOWS_TORMENT",
        "NEW_LEAF",
        "PRECISE_SCISSORS",
        "PHIAL_HOLSTER",
        "WINGED_BOOTS",
        "MASSIVE_SCROLL",
        "LAVA_ROCK",
        "NEOWS_TALISMAN",
        "NUTRITIOUS_OYSTER",
        "POMANDER",
        "SMALL_CAPSULE",
        "STONE_HUMIDIFIER",
        "CURSED_PEARL",
        "HEFTY_TABLET",
        "LARGE_CAPSULE",
        "LEAFY_POULTICE",
        "PRECARIOUS_SHEARS",
        "SILVER_CRUCIBLE",
        "NEOWS_BONES",
        "SCROLL_BOXES",
    }
}
_ANCIENT_RELIC_SOURCE_BY_ID.update({relic_id: "orobas" for relic_id in {
    "ELECTRIC_SHRYMP", "GLASS_EYE", "SAND_CASTLE", "ALCHEMICAL_COFFER", "DRIFTWOOD",
    "RADIANT_PEARL", "SEA_GLASS", "PRISMATIC_GEM", "TOUCH_OF_OROBAS",
}})
_ANCIENT_RELIC_SOURCE_BY_ID.update({relic_id: "pael" for relic_id in {
    "ARCHAIC_TOOTH", "PAELS_CLAW", "PAELS_TOOTH", "PAELS_GROWTH", "PAELS_LEGION",
    "PAELS_FLESH", "PAELS_HORN", "PAELS_TEARS", "PAELS_WING", "PAELS_EYE", "PAELS_BLOOD",
}})
_ANCIENT_RELIC_SOURCE_BY_ID.update({relic_id: "tezcatara" for relic_id in {
    "NUTRITIOUS_SOUP", "VERY_HOT_COCOA", "YUMMY_COOKIE", "BIIIG_HUG", "STORYBOOK",
    "SEAL_OF_GOLD", "TOASTY_MITTENS", "GOLDEN_COMPASS", "PUMPKIN_CANDLE", "TOY_BOX",
}})
_ANCIENT_RELIC_SOURCE_BY_ID.update({relic_id: "nonupeipe" for relic_id in {
    "BLESSED_ANTLER", "BRILLIANT_SCARF", "DELICATE_FROND", "DIAMOND_DIADEM", "FUR_COAT",
    "GLITTER", "JEWELRY_BOX", "LOOMING_FRUIT", "SIGNET_RING",
}})
_ANCIENT_RELIC_SOURCE_BY_ID.update({relic_id: "tanx" for relic_id in {
    "BEAUTIFUL_BRACELET", "CLAWS", "CROSSBOW", "IRON_CLUB", "MEAT_CLEAVER", "SAI",
    "SPIKED_GAUNTLETS", "TANXS_WHISTLE", "THROWING_AXE", "TRI_BOOMERANG", "WAR_HAMMER",
}})
_ANCIENT_RELIC_SOURCE_BY_ID.update({relic_id: "vakuu" for relic_id in {
    "BLOOD_SOAKED_ROSE", "CHOICES_PARADOX", "DISTINGUISHED_CAPE", "FIDDLE", "JEWELED_MASK",
    "LORDS_PARASOL", "MUSIC_BOX", "PRESERVED_FOG", "SERE_TALON", "WHISPERING_EARRING",
}})
_ANCIENT_RELIC_SOURCE_BY_ID.update({relic_id: "darv" for relic_id in {
    "ASTROLABE", "BLACK_STAR", "CALLING_BELL", "DUSTY_TOME", "ECTOPLASM", "EMPTY_CAGE",
    "PANDORAS_BOX", "PHILOSOPHERS_STONE", "RUNIC_PYRAMID", "SNECKO_EYE", "SOZU", "VELVET_CHOKER",
}})


def _compact_query(text: object) -> str:
    return re.sub(r"\s+", "", str(text or "")).lower()


def _sts2_relic_floor_key(text: object) -> str:
    return re.sub(r"[^a-z0-9]", "", str(text or "").lower())


_ANCIENT_RELIC_FLOORS = {
    # Neow, Act 1.
    "ARCANE_SCROLL": "1",
    "BOOMING_CONCH": "1",
    "GOLDEN_PEARL": "1",
    "LEAD_PAPERWEIGHT": "1",
    "LOST_COFFER": "1",
    "NEOWS_TORMENT": "1",
    "NEW_LEAF": "1",
    "PRECISE_SCISSORS": "1",
    "PHIAL_HOLSTER": "1",
    "WINGED_BOOTS": "1",
    "MASSIVE_SCROLL": "1",
    "LAVA_ROCK": "1",
    "NEOWS_TALISMAN": "1",
    "NUTRITIOUS_OYSTER": "1",
    "POMANDER": "1",
    "SMALL_CAPSULE": "1",
    "STONE_HUMIDIFIER": "1",
    "CURSED_PEARL": "1",
    "HEFTY_TABLET": "1",
    "LARGE_CAPSULE": "1",
    "LEAFY_POULTICE": "1",
    "PRECARIOUS_SHEARS": "1",
    "SILVER_CRUCIBLE": "1",
    "NEOWS_BONES": "1",
    "SCROLL_BOXES": "1",
    # Orobas / Pael / Tezcatara, Act 2.
    "ELECTRIC_SHRYMP": "2",
    "GLASS_EYE": "2",
    "SAND_CASTLE": "2",
    "ALCHEMICAL_COFFER": "2",
    "DRIFTWOOD": "2",
    "RADIANT_PEARL": "2",
    "SEA_GLASS": "2",
    "PRISMATIC_GEM": "2",
    "TOUCH_OF_OROBAS": "2",
    "ARCHAIC_TOOTH": "2",
    "PAELS_CLAW": "2",
    "PAELS_TOOTH": "2",
    "PAELS_GROWTH": "2",
    "PAELS_LEGION": "2",
    "PAELS_FLESH": "2",
    "PAELS_HORN": "2",
    "PAELS_TEARS": "2",
    "PAELS_WING": "2",
    "PAELS_EYE": "2",
    "PAELS_BLOOD": "2",
    "NUTRITIOUS_SOUP": "2",
    "VERY_HOT_COCOA": "2",
    "YUMMY_COOKIE": "2",
    "BIIIG_HUG": "2",
    "STORYBOOK": "2",
    "SEAL_OF_GOLD": "2",
    "TOASTY_MITTENS": "2",
    "GOLDEN_COMPASS": "2",
    "PUMPKIN_CANDLE": "2",
    "TOY_BOX": "2",
    # Nonupeipe / Tanx / Vakuu, Act 3.
    "BLESSED_ANTLER": "3",
    "BRILLIANT_SCARF": "3",
    "DELICATE_FROND": "3",
    "DIAMOND_DIADEM": "3",
    "FUR_COAT": "3",
    "GLITTER": "3",
    "JEWELRY_BOX": "3",
    "LOOMING_FRUIT": "3",
    "SIGNET_RING": "3",
    "BEAUTIFUL_BRACELET": "3",
    "CLAWS": "3",
    "CROSSBOW": "3",
    "IRON_CLUB": "3",
    "MEAT_CLEAVER": "3",
    "SAI": "3",
    "SPIKED_GAUNTLETS": "3",
    "TANXS_WHISTLE": "3",
    "THROWING_AXE": "3",
    "TRI_BOOMERANG": "3",
    "WAR_HAMMER": "3",
    "BLOOD_SOAKED_ROSE": "3",
    "CHOICES_PARADOX": "3",
    "DISTINGUISHED_CAPE": "3",
    "FIDDLE": "3",
    "JEWELED_MASK": "3",
    "LORDS_PARASOL": "3",
    "MUSIC_BOX": "3",
    "PRESERVED_FOG": "3",
    "SERE_TALON": "3",
    "WHISPERING_EARRING": "3",
    # Darv can appear after Act 1 or Act 2.
    "ASTROLABE": "2/3",
    "BLACK_STAR": "2/3",
    "CALLING_BELL": "2/3",
    "DUSTY_TOME": "2/3",
    "ECTOPLASM": "2/3",
    "EMPTY_CAGE": "2/3",
    "PANDORAS_BOX": "2/3",
    "PHILOSOPHERS_STONE": "2/3",
    "RUNIC_PYRAMID": "2/3",
    "SNECKO_EYE": "2/3",
    "SOZU": "2/3",
    "VELVET_CHOKER": "2/3",
}
_ANCIENT_RELIC_FLOORS_BY_KEY = {
    _sts2_relic_floor_key(relic_id): floor
    for relic_id, floor in _ANCIENT_RELIC_FLOORS.items()
}


class Sts2StatsPlugin(Star):
    """Slay the Spire 2 / Spire Codex 查询。"""

    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self._sts2_client_obj = None
        self._sts2_pending_choices: dict[str, dict] = {}

    def _cfg(self, key: str, default=None):
        value = self.config.get(key)
        if value is not None:
            return value
        for group in self.config.values():
            if isinstance(group, dict) and group.get(key) is not None:
                return group[key]
        return default

    async def initialize(self):
        for path in (DATA_DIR, STS2_IMAGE_CACHE_DIR, STS2_IMAGES_DIR):
            path.mkdir(parents=True, exist_ok=True)
        configure_cjk_font(str(self._cfg("cjk_font_path", "") or ""))
        await ensure_cjk_font(DATA_DIR)

    async def terminate(self):
        if self._sts2_client_obj is not None:
            await self._sts2_client_obj.close()
        self._sts2_pending_choices.clear()

    def _sts2_enabled(self) -> bool:
        return bool(self._cfg("sts2_enabled", True))

    def _sts2_cfg(self, key: str, default=None):
        return self._cfg(key, default)

    def _sts2_client(self) -> SpireCodexClient:
        client = getattr(self, "_sts2_client_obj", None)
        if client is None:
            client = SpireCodexClient(
                base_url=self._sts2_cfg("sts2_api_base", "https://spire-codex.com/api"),
                lang=self._sts2_cfg("sts2_lang", "zhs"),
                timeout=int(self._sts2_cfg("sts2_request_timeout", 15) or 15),
                ttl_hours=int(self._sts2_cfg("sts2_cache_ttl_hours", 120) or 120),
                rate_limit_per_min=int(self._sts2_cfg("sts2_rate_limit_per_min", 50) or 50),
            )
            self._sts2_client_obj = client
        return client

    def _sts2_guard_msg(self) -> str | None:
        if not self._sts2_enabled():
            return "尖塔查询模块未启用，请在插件配置中开启 sts2_enabled。"
        return None

    def _sts2_full_arg_text(
        self,
        event: AstrMessageEvent,
        command: str,
        arg_text: str,
        *aliases: str,
    ) -> str:
        text = (getattr(event, "message_str", "") or "").strip()
        names = []
        for cmd in (command, *aliases):
            names.extend([cmd, f"/{cmd}"])
        for name in names:
            if text == name:
                return ""
            if text.startswith(name + " "):
                return text[len(name):].strip()
        return (arg_text or "").strip()

    def _sts2_max_list_results(self) -> int:
        return max(1, min(20, int(self._sts2_cfg("sts2_max_list_results", 10) or 10)))

    def _sts2_power_table_limit(self) -> int:
        raw = self._sts2_cfg("sts2_power_table_limit", 120)
        value = int(raw or 120)
        if value == 30:
            value = 120
        return max(10, min(200, value))

    def _resolve_sts2_character(self, arg: str) -> tuple[str, str] | None:
        key = arg.strip().lower()
        return _CHARACTER_ALIASES.get(key)

    def _sts2_metric_character(self, character: str | None) -> str | None:
        value = str(character or "").strip()
        return value.upper() if value else None

    def _resolve_sts2_power_scope(self, arg: str) -> tuple[str, str, str | None] | None:
        key = arg.strip().lower()
        if key in {"先古", "先古遗物", "古遗物", "ancient", "ancientrelic", "ancientrelics"}:
            return ("ancient_help", "先古", None)
        ancient_source = _ANCIENT_RELIC_SOURCE_ALIASES.get(key)
        if ancient_source:
            return ("ancient_source", ancient_source[1], ancient_source[0])
        if key in _NEOW_POWER_ALIASES:
            return ("ancient_source", "涅奥", "neow")
        if key in _RELIC_POWER_ALIASES:
            return ("relics", "遗物", None)
        if key in _COMMON_POWER_ALIASES:
            return ("common", "通用", None)
        if key in _COLORLESS_POWER_ALIASES:
            return ("colorless", "无色", None)
        if key in _CURSE_POWER_ALIASES:
            return ("curse", "诅咒", None)
        if key in _MULTIPLAYER_POWER_ALIASES:
            return ("multiplayer", "多人", None)
        character = _CHARACTER_ALIASES.get(key)
        if character:
            return ("character", character[1], character[0])
        return None

    def _sts2_is_common_card(self, card: dict[str, Any]) -> bool:
        color = str(card.get("color") or "").lower()
        return color == "colorless" or color == "curse" or self._sts2_is_universal_ancient_card(card)

    def _sts2_is_universal_ancient_card(self, card: dict[str, Any]) -> bool:
        color = str(card.get("color") or "").lower()
        rarity_key = str(card.get("rarity_key") or "").lower()
        rarity = str(card.get("rarity") or "")
        return color == "event" and (rarity_key == "ancient" or rarity == "先古")

    def _sts2_is_multiplayer_card(self, card: dict[str, Any]) -> bool:
        if str(card.get("id") or "").upper() in _MULTIPLAYER_CARD_IDS:
            return True
        if str(card.get("target") or "") in _MULTIPLAYER_CARD_TARGETS:
            return True
        text = "\n".join(
            str(card.get(k) or "")
            for k in ("description", "description_raw")
        )
        return any(marker in text for marker in _MULTIPLAYER_CARD_MARKERS)

    def _sts2_card_group_label(self, card: dict[str, Any]) -> str:
        color = str(card.get("color") or "").lower()
        rarity = str(card.get("rarity") or "")
        labels: list[str] = []
        if color == "colorless":
            labels.append("无色")
        elif color == "curse":
            labels.append("诅咒")
        elif color == "event":
            labels.append("先古" if rarity == "先古" else "事件")
        elif rarity == "先古":
            labels.append("先古")
        elif rarity or color:
            labels.append(rarity or color)
        if self._sts2_is_multiplayer_card(card):
            labels.append("多人")
        return " ".join(f"【{label}】" for label in labels)

    def _sts2_card_name_color(self, card: dict[str, Any]) -> tuple[int, int, int]:
        rarity_key = str(card.get("rarity_key") or "").lower()
        rarity = str(card.get("rarity") or "").lower()
        if rarity_key in {"rare"} or rarity in {"稀有", "稀有卡", "稀有牌"}:
            return (236, 190, 84)
        if rarity_key in {"uncommon"} or rarity in {"罕见", "罕见卡", "罕见牌"}:
            return (106, 174, 255)
        return (235, 239, 248)

    def _sts2_card_type_key(self, card: dict[str, Any]) -> str:
        color = str(card.get("color") or "").strip().lower()
        if color in {"curse", "status", "event"}:
            return "unframed"
        type_key = str(card.get("type_key") or card.get("type") or "").strip().lower()
        aliases = {
            "攻击": "attack",
            "技能": "skill",
            "能力": "power",
            "状态": "unframed",
            "诅咒": "unframed",
        }
        return aliases.get(type_key, type_key or "other")

    def _sts2_relic_group_label(self, relic: dict[str, Any]) -> str:
        rarity = str(relic.get("rarity") or relic.get("tier") or "").replace("遗物", "")
        layer = self._sts2_ancient_relic_layer(relic)
        if layer and rarity == "先古":
            labels = [f"先古·{layer}层"]
        else:
            labels = [rarity] if rarity else []
        return " ".join(f"【{label}】" for label in labels)

    def _sts2_ancient_relic_layer(self, relic: dict[str, Any]) -> str | None:
        if str(relic.get("rarity_key") or "") != "Ancient" and str(relic.get("rarity") or "") != "先古遗物":
            return None
        relic_id = str(relic.get("id") or "").upper()
        return _ANCIENT_RELIC_FLOORS.get(relic_id) or _ANCIENT_RELIC_FLOORS_BY_KEY.get(_sts2_relic_floor_key(relic_id))

    def _sts2_image_url_candidates(self, item: dict[str, Any]) -> list[str]:
        client = self._sts2_client()
        type_key = str(item.get("_sts2_type") or item.get("_type") or "")
        fields = [
            "image_url_card_zhs",
            "image_url_card_zh",
            "image_url_zhs",
            "image_url_zh",
            "image_url_card",
            "image_url",
            "beta_image_url",
        ]
        urls: list[str] = []
        seen: set[str] = set()

        def add(raw: object) -> None:
            url = normalize_sts2_url(client.base_url, raw)
            if url and url not in seen:
                seen.add(url)
                urls.append(url)

        def add_card_variants(raw: object) -> None:
            url = normalize_sts2_url(client.base_url, raw)
            if not url:
                return
            if "/cards-full/stable/" in url and "/cards-full/stable/zhs/" not in url:
                add(url.replace("/cards-full/stable/", "/cards-full/stable/zhs/", 1))
            add(url)

        for field in fields:
            raw = item.get(field)
            if (type_key == "cards" or item.get("image_url_card")) and field == "image_url_card":
                add_card_variants(raw)
            else:
                add(raw)
        return urls

    async def _sts2_icons(self, items: list[dict[str, Any]]) -> list[bytes | None]:
        async with aiohttp.ClientSession(
            headers={"User-Agent": "Mozilla/5.0"},
            trust_env=True,
        ) as session:
            sem = asyncio.Semaphore(8)

            async def fetch(item: dict[str, Any]) -> bytes | None:
                urls = self._sts2_image_url_candidates(item)
                if not urls:
                    return None
                oid = str(item.get("id") or urls[0])
                async with sem:
                    for url in urls:
                        try:
                            data = await download_icon(session, url, oid=f"sts2_{oid}", cache_dir=STS2_IMAGE_CACHE_DIR)
                            if data:
                                return data
                        except Exception as e:
                            logger.debug(f"[sts2_stats] 图标下载失败 {oid}: {e}")
                    return None

            return await asyncio.gather(*(fetch(item) for item in items))

    def _sts2_exact_results(
        self,
        query: str,
        results: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        q = _compact_query(query)
        exact: list[dict[str, Any]] = []
        for item in results:
            names = [
                item.get("name"),
                item.get("id"),
            ]
            if any(_compact_query(strip_sts2_markup(v)) == q for v in names):
                exact.append(item)
        return exact

    def _sts2_without_shadowed_powers(
        self,
        results: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        primary_ids: set[str] = set()
        primary_names: set[str] = set()
        for item in results:
            if item.get("_sts2_type") == "powers":
                continue
            item_id = _compact_query(item.get("id"))
            item_name = _compact_query(strip_sts2_markup(item.get("name")))
            if item_id:
                primary_ids.add(item_id)
            if item_name:
                primary_names.add(item_name)

        return [
            item
            for item in results
            if item.get("_sts2_type") != "powers"
            or (
                _compact_query(item.get("id")) not in primary_ids
                and _compact_query(strip_sts2_markup(item.get("name"))) not in primary_names
            )
        ]

    def _sts2_preferred_exact_result(self, exact: list[dict[str, Any]]) -> dict[str, Any] | None:
        if not exact:
            return None
        ordered = sorted(
            exact,
            key=lambda item: (
                _STS2_GENERIC_TYPE_PRIORITY.get(str(item.get("_sts2_type") or ""), 50),
                str(item.get("name") or ""),
            ),
        )
        exact_cards = [item for item in ordered if item.get("_sts2_type") == "cards"]
        if exact_cards:
            # Card effects commonly create a power with the same localized name.
            # An exact generic query should resolve to the playable card itself.
            return exact_cards[0]
        best = ordered[0]
        if len(ordered) == 1:
            return best
        best_priority = _STS2_GENERIC_TYPE_PRIORITY.get(str(best.get("_sts2_type") or ""), 50)
        next_priority = _STS2_GENERIC_TYPE_PRIORITY.get(str(ordered[1].get("_sts2_type") or ""), 50)
        if best_priority < 9 and next_priority >= 9:
            return best
        return None

    async def _sts2_icon(self, item: dict[str, Any]) -> bytes | None:
        urls = self._sts2_image_url_candidates(item)
        if not urls:
            return None
        oid = str(item.get("id") or urls[0])
        async with aiohttp.ClientSession(
            headers={"User-Agent": "Mozilla/5.0"},
            trust_env=True,
        ) as session:
            for url in urls:
                data = await download_icon(session, url, oid=f"sts2_{oid}", cache_dir=STS2_IMAGE_CACHE_DIR)
                if data:
                    return data
        return None

    async def _sts2_render_detail_png(self, item: dict[str, Any]) -> bytes:
        type_key = item.get("_sts2_type") or item.get("_type") or ""
        if not type_key:
            for key in STS2_ENTITY_TYPES:
                if item in await self._sts2_client().fetch_list(key):
                    type_key = key
                    break
        if type_key in {"cards", "relics"} and "_sts2_winrate" not in item:
            try:
                item = dict(item)
                item["_sts2_winrate"] = await self._sts2_client().winrate_summary(
                    entity_type=type_key,
                    entity_id=str(item.get("id") or ""),
                    ascension=int(self._sts2_cfg("sts2_default_ascension", 10) or 10),
                )
            except Exception as e:
                logger.warning(f"[sts2_stats] 胜率数据拉取失败: {e}")
                item["_sts2_winrate_error"] = True
        icon = await self._sts2_icon(item)
        return await asyncio.to_thread(render_sts2_detail, item, type_key, icon)

    async def _sts2_send_detail(self, event: AstrMessageEvent, item: dict[str, Any]):
        type_key = item.get("_sts2_type") or item.get("_type") or "item"
        png = await self._sts2_render_detail_png(item)
        path = STS2_IMAGES_DIR / f"sts2_detail_{type_key}.png"
        await save_png(path, png)
        yield event.chain_result([Comp.Image.fromFileSystem(str(path))])

    async def _sts2_resolve_one_query(
        self,
        query: str,
        type_key: str | None,
    ) -> tuple[dict[str, Any] | None, list[dict[str, Any]], int]:
        results = await self._sts2_client().search(
            query,
            type_key=type_key,
            limit=max(30, self._sts2_max_list_results()),
        )
        if type_key is None:
            results = self._sts2_without_shadowed_powers(results)
        if not results:
            return None, [], 0
        if len(results) == 1:
            return results[0], [], 1
        exact = self._sts2_exact_results(query, results)
        preferred = self._sts2_preferred_exact_result(exact)
        if preferred is not None:
            return preferred, [], len(results)
        if len(exact) == 1:
            return exact[0], [], len(results)
        return None, exact or results, len(exact) or len(results)

    def _sts2_multi_queries(self, query: str) -> list[str]:
        parts = [p.strip() for p in _STS2_MULTI_QUERY_SPLIT_RE.split(query) if p.strip()]
        if len(parts) <= 1:
            return []
        return parts[:6]

    async def _sts2_query_multi_common(
        self,
        event: AstrMessageEvent,
        queries: list[str],
        type_key: str | None,
    ):
        async for ret in self._sts2_continue_multi_query(event, [], queries, type_key):
            yield ret

    async def _sts2_continue_multi_query(
        self,
        event: AstrMessageEvent,
        resolved_items: list[dict[str, Any]],
        queries: list[str],
        type_key: str | None,
    ):
        items = list(resolved_items)
        try:
            for index, part in enumerate(queries):
                item, candidates, total = await self._sts2_resolve_one_query(part, type_key)
                if item is not None:
                    items.append(item)
                    continue
                if not candidates:
                    yield event.plain_result(f"未找到「{part}」相关条目，已取消拼接查询。")
                    return
                yield event.plain_result(f"「{part}」有 {total} 个候选，请先补全名称或用 /选择 序号。")
                pending_context = {
                    "multi_items": items,
                    "remaining_queries": queries[index + 1 :],
                    "type_key": type_key,
                }
                async for ret in self._sts2_handle_results(
                    event,
                    part,
                    candidates,
                    pending_context=pending_context,
                ):
                    yield ret
                return
        except Exception as e:
            logger.error(f"[sts2_stats] 多条查询失败: {e}", exc_info=True)
            yield event.plain_result("数据源暂时无法访问，请稍后再试。")
            return
        try:
            pngs = [await self._sts2_render_detail_png(item) for item in items]
            bundle = await asyncio.to_thread(render_sts2_detail_bundle, pngs)
            path = STS2_IMAGES_DIR / "sts2_detail_bundle.png"
            await save_png(path, bundle)
        except Exception as e:
            logger.error(f"[sts2_stats] 多条详情图生成失败: {e}", exc_info=True)
            yield event.plain_result("详情图生成失败，请稍后再试。")
            return
        yield event.chain_result([Comp.Image.fromFileSystem(str(path))])

    async def _sts2_handle_results(
        self,
        event: AstrMessageEvent,
        query: str,
        results: list[dict[str, Any]],
        pending_context: dict[str, Any] | None = None,
    ):
        if not results:
            yield event.plain_result(f"未找到「{query}」相关条目，请换个关键词。")
            return
        if len(results) == 1:
            async for ret in self._sts2_send_detail(event, results[0]):
                yield ret
            return

        exact = self._sts2_exact_results(query, results)
        preferred = self._sts2_preferred_exact_result(exact)
        if preferred is not None:
            async for ret in self._sts2_send_detail(event, preferred):
                yield ret
            return
        if len(exact) == 1:
            async for ret in self._sts2_send_detail(event, exact[0]):
                yield ret
            return
        if len(exact) > 1:
            results = exact

        limit = self._sts2_max_list_results()
        shown = results[:limit]
        pending = getattr(self, "_sts2_pending_choices", None)
        if pending is None:
            pending = {}
            self._sts2_pending_choices = pending
        key = f"{event.unified_msg_origin}:{event.get_sender_id()}"
        state = {
            "created_at": time.time(),
            "query": query,
            "items": shown,
        }
        if pending_context:
            state.update(pending_context)
        pending[key] = state
        icon_map: dict[str, bytes | None] = {}
        for idx, item in enumerate(shown):
            icon_map[str(idx)] = await self._sts2_icon(item)
        png = await asyncio.to_thread(
            render_sts2_list,
            shown,
            query,
            len(results),
            icon_map,
        )
        path = STS2_IMAGES_DIR / "sts2_search_list.png"
        await save_png(path, png)
        yield event.chain_result([Comp.Image.fromFileSystem(str(path))])

    async def _sts2_query_common(self, event: AstrMessageEvent, query: str, type_key: str | None = None):
        if msg := self._sts2_guard_msg():
            yield event.plain_result(msg)
            return
        if not query:
            scope = "查询" if type_key is None else STS2_ENTITY_TYPES[type_key]["label"]
            yield event.plain_result(f"用法：/尖塔{scope} <关键词>")
            return
        multi_queries = self._sts2_multi_queries(query)
        if multi_queries:
            async for ret in self._sts2_query_multi_common(event, multi_queries, type_key):
                yield ret
            return
        try:
            results = await self._sts2_client().search(
                query,
                type_key=type_key,
                limit=max(30, self._sts2_max_list_results()),
            )
            if type_key is None:
                results = self._sts2_without_shadowed_powers(results)
        except Exception as e:
            logger.error(f"[sts2_stats] 查询失败: {e}", exc_info=True)
            yield event.plain_result("数据源暂时无法访问，请稍后再试。")
            return
        async for ret in self._sts2_handle_results(event, query, results):
            yield ret

    async def _sts2_reset_cache_common(self, event: AstrMessageEvent):
        if msg := self._sts2_guard_msg():
            yield event.plain_result(msg)
            return
        count = self._sts2_client().clear_cache()
        pending = getattr(self, "_sts2_pending_choices", None)
        if isinstance(pending, dict):
            pending.clear()
        yield event.plain_result(f"尖塔缓存已清空：{count} 项数据缓存；卡图缓存保留，下一次查询会重新拉取。")

    @filter.command("尖塔", alias={"杀戮尖塔", "尖塔帮助", "塔"})
    async def sts2_overview(self, event: AstrMessageEvent, arg_text: str = ""):
        arg = self._sts2_full_arg_text(event, "尖塔", arg_text, "杀戮尖塔", "尖塔帮助", "塔")
        if arg:
            if _compact_query(arg) in {"reset", "重置", "清缓存", "清空缓存", "重置缓存"}:
                async for ret in self._sts2_reset_cache_common(event):
                    yield ret
                return
            async for ret in self._sts2_query_common(event, arg, None):
                yield ret
            return
        if msg := self._sts2_guard_msg():
            yield event.plain_result(msg)
            return
        png = await asyncio.to_thread(render_sts2_overview)
        path = STS2_IMAGES_DIR / "sts2_overview.png"
        await save_png(path, png)
        yield event.chain_result([Comp.Image.fromFileSystem(str(path))])

    @filter.command("尖塔查询", alias={"尖塔搜索"})
    async def sts2_query(self, event: AstrMessageEvent, arg_text: str = ""):
        arg = self._sts2_full_arg_text(event, "尖塔查询", arg_text, "尖塔搜索")
        async for ret in self._sts2_query_common(event, arg, None):
            yield ret

    async def _sts2_winrate_common(self, event: AstrMessageEvent, query: str):
        if msg := self._sts2_guard_msg():
            yield event.plain_result(msg)
            return
        if not query:
            yield event.plain_result("用法：/尖塔胜率 <卡牌名或遗物名>（默认 A10）")
            return
        client = self._sts2_client()
        try:
            results = await client.search(query, type_key=None, limit=30)
            results = [r for r in results if r.get("_sts2_type") in {"cards", "relics"}]
        except Exception as e:
            logger.error(f"[sts2_stats] 胜率查询失败: {e}", exc_info=True)
            yield event.plain_result("数据源暂时无法访问，请稍后再试。")
            return
        if not results:
            yield event.plain_result(f"未找到「{query}」对应的卡牌或遗物。")
            return
        exact = self._sts2_exact_results(query, results)
        item = exact[0] if exact else results[0]
        if len(results) > 1 and not exact:
            shown = results[: self._sts2_max_list_results()]
            pending = getattr(self, "_sts2_pending_choices", None)
            if pending is None:
                pending = {}
                self._sts2_pending_choices = pending
            key = f"{event.unified_msg_origin}:{event.get_sender_id()}"
            pending[key] = {
                "created_at": time.time(),
                "query": query,
                "items": shown,
            }
            icon_map: dict[str, bytes | None] = {}
            for idx, row in enumerate(shown):
                icon_map[str(idx)] = await self._sts2_icon(row)
            png = await asyncio.to_thread(render_sts2_list, shown, query, len(results), icon_map)
            path = STS2_IMAGES_DIR / "sts2_winrate_candidates.png"
            await save_png(path, png)
            yield event.chain_result([Comp.Image.fromFileSystem(str(path))])
            return
        try:
            type_key = str(item.get("_sts2_type"))
            stats = await client.winrate_summary(
                entity_type=type_key,
                entity_id=str(item.get("id") or ""),
                ascension=int(self._sts2_cfg("sts2_default_ascension", 10) or 10),
            )
        except Exception as e:
            logger.error(f"[sts2_stats] 胜率数据拉取失败: {e}", exc_info=True)
            yield event.plain_result("胜率数据暂时无法访问，请稍后再试。")
            return
        png = await asyncio.to_thread(
            render_sts2_winrate,
            item=item,
            type_label=str(item.get("_sts2_type_label") or ""),
            stats=stats,
        )
        path = STS2_IMAGES_DIR / "sts2_winrate.png"
        await save_png(path, png)
        yield event.chain_result([Comp.Image.fromFileSystem(str(path))])

    def _sts2_is_neow_relic(self, relic: dict[str, Any]) -> bool:
        return self._sts2_is_ancient_source_relic(relic, "neow")

    def _sts2_is_ancient_relic(self, relic: dict[str, Any]) -> bool:
        return str(relic.get("rarity_key") or "") == "Ancient" or str(relic.get("rarity") or "") == "先古遗物"

    def _sts2_is_ancient_source_relic(self, relic: dict[str, Any], source: str) -> bool:
        relic_id = str(relic.get("id") or "").upper()
        return self._sts2_is_ancient_relic(relic) and _ANCIENT_RELIC_SOURCE_BY_ID.get(relic_id) == source

    async def _sts2_character_icon(self, character: str) -> bytes | None:
        try:
            characters = await self._sts2_client().fetch_list("characters")
            item = next(
                (
                    row
                    for row in characters
                    if str(row.get("id") or "").lower() == character
                    or str(row.get("name") or "").lower() == character
                ),
                None,
            )
            return await self._sts2_icon(item) if item else None
        except Exception as e:
            logger.debug(f"[sts2_stats] 角色头像拉取失败 {character}: {e}")
            return None

    async def _sts2_character_relic_power_table_common(
        self,
        event: AstrMessageEvent,
        *,
        command: str,
        reverse: bool,
        relic_scope: str,
        scope_label: str,
        scope_slug: str,
        predicate,
    ):
        try:
            relics = await self._sts2_client().fetch_list("relics")
            selected_relics = {
                str(relic.get("id")): relic
                for relic in relics
                if predicate(relic)
            }
        except Exception as e:
            logger.error(f"[sts2_stats] {command}{scope_label}遗物查询失败: {e}", exc_info=True)
            yield event.plain_result("数据源暂时无法访问，请稍后再试。")
            return

        if not selected_relics:
            yield event.plain_result(f"暂无{scope_label}遗物数据。")
            return

        min_picks = int(self._sts2_cfg("sts2_power_table_min_picks", 100) or 100)

        metric_tasks = [
            self._sts2_client().entity_metric_map(
                "relics",
                bracket="solo:a10",
                character=self._sts2_metric_character(character),
            )
            for character, _ in _STS2_CHARACTER_ORDER
        ]
        score_maps = await asyncio.gather(*metric_tasks, return_exceptions=True)

        table_specs: list[dict[str, Any]] = []
        limit = self._sts2_power_table_limit()
        for (character, character_label), scores in zip(_STS2_CHARACTER_ORDER, score_maps):
            metric_character = self._sts2_metric_character(character)
            if isinstance(scores, Exception):
                logger.warning(
                    f"[sts2_stats] {scope_label}遗物角色排行失败 {metric_character}: {scores}"
                )
                continue
            rows: list[dict[str, Any]] = []
            for eid, entity in selected_relics.items():
                stat = scores.get(eid) if isinstance(scores.get(eid), dict) else None
                if not isinstance(stat, dict):
                    continue
                if int(stat.get("picks") or 0) < min_picks:
                    continue
                rows.append({
                    "id": eid,
                    "name": entity.get("name") or eid,
                    "win_rate": stat.get("win_rate"),
                    "picks": stat.get("picks"),
                    "wins": stat.get("wins"),
                    "pick_rate": stat.get("pick_rate"),
                    "group": self._sts2_relic_group_label(entity),
                })
            rows.sort(
                key=lambda row: (float(row.get("win_rate") or 0), int(row.get("picks") or 0)),
                reverse=reverse,
            )
            total_rows = len(rows)
            rows = rows[:limit]
            if rows:
                table_specs.append({
                    "character": character,
                    "character_label": character_label,
                    "metric_character": metric_character,
                    "rows": rows,
                    "total_rows": total_rows,
                })

        if not table_specs:
            yield event.plain_result(f"暂无{scope_label}遗物 A10 单人角色胜率排行数据。")
            return

        used_ids = list(dict.fromkeys(
            str(row["id"])
            for spec in table_specs
            for row in spec["rows"]
        ))
        relic_icons = await self._sts2_icons([selected_relics[eid] for eid in used_ids])
        icon_by_id = {
            eid: icon
            for eid, icon in zip(used_ids, relic_icons)
        }
        character_icons = await asyncio.gather(
            *(self._sts2_character_icon(str(spec["character"])) for spec in table_specs),
            return_exceptions=True,
        )

        images: list[bytes] = []
        for spec, character_icon in zip(table_specs, character_icons):
            rows = spec["rows"]
            for row in rows:
                row["icon"] = icon_by_id.get(str(row["id"]))
            footnote = (
                "数据来源：Spire Codex runs/metrics/relics"
                f"?bracket=solo:a10&character={spec['metric_character']}；"
                f"仅统计{spec['character_label']}单人存档"
            )
            if spec["total_rows"] > len(rows):
                footnote = f"{footnote}；符合条件 {spec['total_rows']} 个，显示前 {len(rows)} 个"
            else:
                footnote = f"{footnote}；共 {len(rows)} 个"
            icon = character_icon if isinstance(character_icon, bytes) else None
            images.append(await asyncio.to_thread(
                render_sts2_card_power_table,
                title=command,
                character_label=f"{spec['character_label']} · {relic_scope}",
                rows=rows,
                ascension_label="A10 · SOLO单人样本",
                subtitle=f"{relic_scope}遗物胜率排行",
                footnote=footnote,
                title_icon=icon,
            ))

        bundle = await asyncio.to_thread(render_sts2_power_table_bundle, images, direction="horizontal")
        path = STS2_IMAGES_DIR / f"sts2_{scope_slug}_power_table.png"
        await save_png(path, bundle)
        yield event.chain_result([Comp.Image.fromFileSystem(str(path))])

    async def _sts2_neow_power_table_common(
        self,
        event: AstrMessageEvent,
        *,
        command: str,
        reverse: bool,
    ):
        async for ret in self._sts2_character_relic_power_table_common(
            event,
            command=command,
            reverse=reverse,
            relic_scope="涅奥",
            scope_label="涅奥初始",
            scope_slug="neow",
            predicate=self._sts2_is_neow_relic,
        ):
            yield ret

    async def _sts2_ancient_relic_power_table_common(
        self,
        event: AstrMessageEvent,
        *,
        command: str,
        reverse: bool,
        source: str,
        source_label: str,
    ):
        async for ret in self._sts2_character_relic_power_table_common(
            event,
            command=command,
            reverse=reverse,
            relic_scope=source_label,
            scope_label=source_label,
            scope_slug=f"ancient_{source}",
            predicate=lambda relic: self._sts2_is_ancient_source_relic(relic, source),
        ):
            yield ret

    @filter.command("尖塔胜率")
    async def sts2_winrate(self, event: AstrMessageEvent, arg_text: str = ""):
        arg = self._sts2_full_arg_text(event, "尖塔胜率", arg_text)
        async for ret in self._sts2_winrate_common(event, arg):
            yield ret

    @filter.command("愤怒")
    async def sts2_anger(self, event: AstrMessageEvent):
        if msg := self._sts2_guard_msg():
            yield event.plain_result(msg)
            return
        yield event.plain_result("card ANGER discard")

    async def _sts2_power_table_common(
        self,
        event: AstrMessageEvent,
        arg_text: str,
        *,
        command: str,
        reverse: bool,
    ):
        if msg := self._sts2_guard_msg():
            yield event.plain_result(msg)
            return
        arg = self._sts2_full_arg_text(event, command, arg_text)
        resolved = self._resolve_sts2_power_scope(arg)
        if not resolved:
            yield event.plain_result(f"用法：/{command} 战士|猎人|储君|骨妹|鸡煲|通用|无色|诅咒|多人|遗物|涅奥|先古")
            return
        scope, label, character = resolved
        if scope == "ancient_help":
            yield event.plain_result(
                f"先古遗物表请指定来源：/{command} 涅奥|欧洛巴斯|佩尔|特兹卡塔拉|诺奴佩普|坦克斯|瓦库|达弗"
            )
            return
        if scope == "ancient_source":
            if character == "neow":
                async for ret in self._sts2_neow_power_table_common(event, command=command, reverse=reverse):
                    yield ret
                return
            async for ret in self._sts2_ancient_relic_power_table_common(
                event,
                command=command,
                reverse=reverse,
                source=str(character),
                source_label=label,
            ):
                yield ret
            return
        entity_type = "relics" if scope == "relics" else "cards"
        metric_character = self._sts2_metric_character(character) if scope == "character" else None
        try:
            if scope == "multiplayer":
                entities, scores = await asyncio.gather(
                    self._sts2_client().fetch_list("cards"),
                    self._sts2_client().entity_metric_map("cards", bracket="2p:a10"),
                )
            else:
                entities, scores = await asyncio.gather(
                    self._sts2_client().fetch_list(entity_type),
                    self._sts2_client().entity_metric_map(
                        entity_type,
                        bracket="solo:a10",
                        character=metric_character,
                    ),
                )
        except Exception as e:
            logger.error(f"[sts2_stats] {command}查询失败: {e}", exc_info=True)
            yield event.plain_result("数据源暂时无法访问，请稍后再试。")
            return
        if scope == "relics":
            entity_map = {
                str(r.get("id")): r
                for r in entities
            }
            subtitle = "遗物胜率排行"
            ascension_label = "A10 · SOLO单人样本"
            footnote = "数据来源：Spire Codex runs/metrics/relics?bracket=solo:a10；仅统计单人存档"
        elif scope == "multiplayer":
            entity_map = {
                str(c.get("id")): c
                for c in entities
                if self._sts2_is_multiplayer_card(c)
            }
            subtitle = "多人卡牌胜率排行"
            ascension_label = "A10 · P2双人样本"
            footnote = "数据来源：Spire Codex runs/metrics/cards?bracket=2p:a10；仅统计双人存档"
        elif scope in {"common", "colorless", "curse"}:
            if scope == "common":
                predicate = self._sts2_is_common_card
                subtitle = "通用卡牌胜率排行"
                footnote = "数据来源：Spire Codex runs/metrics/cards?bracket=solo:a10；统计无色、通用先古、诅咒卡；仅统计单人存档"
            elif scope == "colorless":
                predicate = lambda card: str(card.get("color") or "").lower() == "colorless"
                subtitle = "无色卡牌胜率排行"
                footnote = "数据来源：Spire Codex runs/metrics/cards?bracket=solo:a10；仅统计无色卡；仅统计单人存档"
            else:
                predicate = lambda card: str(card.get("color") or "").lower() == "curse"
                subtitle = "诅咒卡牌胜率排行"
                footnote = "数据来源：Spire Codex runs/metrics/cards?bracket=solo:a10；仅统计诅咒卡；仅统计单人存档"
            entity_map = {
                str(c.get("id")): c
                for c in entities
                if predicate(c)
            }
            ascension_label = "A10 · SOLO单人样本"
        else:
            entity_map = {
                str(c.get("id")): c
                for c in entities
                if c.get("color") == character and not self._sts2_is_common_card(c)
            }
            subtitle = "角色卡牌胜率排行"
            ascension_label = "A10 · SOLO单人样本"
            footnote = (
                "数据来源：Spire Codex runs/metrics/cards"
                f"?bracket=solo:a10&character={metric_character}；"
                "仅统计该角色卡池与该角色单人存档"
            )
        score_fallbacks: dict[str, dict[str, Any]] = {}
        rows: list[dict[str, Any]] = []
        min_picks = int(self._sts2_cfg("sts2_power_table_min_picks", 100) or 100)
        include_multiplayer = scope == "multiplayer"
        for eid, entity in entity_map.items():
            stat = scores.get(eid) if isinstance(scores.get(eid), dict) else score_fallbacks.get(eid)
            if not isinstance(stat, dict):
                continue
            if scope not in {"relics", "multiplayer"} and self._sts2_is_multiplayer_card(entity) and not include_multiplayer:
                continue
            if int(stat.get("picks") or 0) < min_picks:
                continue
            rows.append({
                "id": eid,
                "name": entity.get("name") or eid,
                "win_rate": stat.get("win_rate"),
                "picks": stat.get("picks"),
                "wins": stat.get("wins"),
                "pick_rate": stat.get("pick_rate"),
                "name_color": self._sts2_card_name_color(entity) if scope == "character" else None,
                "card_type": self._sts2_card_type_key(entity) if scope != "relics" else None,
                "group": (
                    self._sts2_relic_group_label(entity)
                    if scope == "relics"
                    else self._sts2_card_group_label(entity)
                    if scope in {"common", "colorless", "curse", "multiplayer"}
                    else "【多人】"
                    if self._sts2_is_multiplayer_card(entity)
                    else ""
                ),
            })
        rows.sort(
            key=lambda r: (float(r.get("win_rate") or 0), int(r.get("picks") or 0)),
            reverse=reverse,
        )
        total_rows = len(rows)
        rows = rows[: self._sts2_power_table_limit()]
        if not rows:
            yield event.plain_result(f"暂无「{label}」胜率排行数据。")
            return
        if scope == "relics":
            icons = await self._sts2_icons([entity_map[str(row["id"])] for row in rows])
            for row, icon in zip(rows, icons):
                row["icon"] = icon
        if total_rows > len(rows):
            footnote = f"{footnote}；符合条件 {total_rows} 张，显示前 {len(rows)} 张"
        else:
            footnote = f"{footnote}；共 {len(rows)} 张"
        title_icon = await self._sts2_character_icon(character) if scope == "character" and character else None
        png = await asyncio.to_thread(
            render_sts2_card_power_table,
            title=command,
            character_label=label,
            rows=rows,
            ascension_label=ascension_label,
            subtitle=subtitle,
            footnote=footnote,
            title_icon=title_icon,
        )
        path = STS2_IMAGES_DIR / "sts2_power_table.png"
        await save_png(path, png)
        yield event.chain_result([Comp.Image.fromFileSystem(str(path))])

    @filter.command("从夯到拉")
    async def sts2_power_table(self, event: AstrMessageEvent, arg_text: str = ""):
        async for ret in self._sts2_power_table_common(
            event,
            arg_text,
            command="从夯到拉",
            reverse=True,
        ):
            yield ret

    @filter.command("从拉到夯")
    async def sts2_reverse_power_table(self, event: AstrMessageEvent, arg_text: str = ""):
        async for ret in self._sts2_power_table_common(
            event,
            arg_text,
            command="从拉到夯",
            reverse=False,
        ):
            yield ret

    @filter.regex(r"^/?尖塔(查询|搜索|卡牌|遗物|怪物|药水|事件|能力|角色)([^\s].*)$")
    async def sts2_regex_query(self, event: AstrMessageEvent):
        text = (event.message_str or "").strip()
        match = re.match(r"^/?尖塔(查询|搜索|卡牌|遗物|怪物|药水|事件|能力|角色)([^\s].*)$", text)
        if not match:
            return
        kind, arg = match.group(1), match.group(2).strip()
        type_key = None if kind in {"查询", "搜索"} else _CMD_TO_TYPE.get(kind)
        async for ret in self._sts2_query_common(event, arg, type_key):
            yield ret

    @filter.command("尖塔卡牌")
    async def sts2_cards(self, event: AstrMessageEvent, arg_text: str = ""):
        arg = self._sts2_full_arg_text(event, "尖塔卡牌", arg_text)
        async for ret in self._sts2_query_common(event, arg, "cards"):
            yield ret

    @filter.command("尖塔遗物")
    async def sts2_relics(self, event: AstrMessageEvent, arg_text: str = ""):
        arg = self._sts2_full_arg_text(event, "尖塔遗物", arg_text)
        async for ret in self._sts2_query_common(event, arg, "relics"):
            yield ret

    @filter.command("尖塔怪物")
    async def sts2_monsters(self, event: AstrMessageEvent, arg_text: str = ""):
        arg = self._sts2_full_arg_text(event, "尖塔怪物", arg_text)
        async for ret in self._sts2_query_common(event, arg, "monsters"):
            yield ret

    @filter.command("尖塔药水")
    async def sts2_potions(self, event: AstrMessageEvent, arg_text: str = ""):
        arg = self._sts2_full_arg_text(event, "尖塔药水", arg_text)
        async for ret in self._sts2_query_common(event, arg, "potions"):
            yield ret

    @filter.command("尖塔事件")
    async def sts2_events(self, event: AstrMessageEvent, arg_text: str = ""):
        arg = self._sts2_full_arg_text(event, "尖塔事件", arg_text)
        async for ret in self._sts2_query_common(event, arg, "events"):
            yield ret

    @filter.command("尖塔能力")
    async def sts2_powers(self, event: AstrMessageEvent, arg_text: str = ""):
        arg = self._sts2_full_arg_text(event, "尖塔能力", arg_text)
        async for ret in self._sts2_query_common(event, arg, "powers"):
            yield ret

    @filter.command("尖塔角色")
    async def sts2_characters(self, event: AstrMessageEvent, arg_text: str = ""):
        arg = self._sts2_full_arg_text(event, "尖塔角色", arg_text)
        async for ret in self._sts2_query_common(event, arg, "characters"):
            yield ret

    @filter.command("尖塔选择", alias={"尖塔选", "选择"})
    async def sts2_select(self, event: AstrMessageEvent, arg_text: str = ""):
        if msg := self._sts2_guard_msg():
            yield event.plain_result(msg)
            return
        arg = self._sts2_full_arg_text(event, "尖塔选择", arg_text, "尖塔选", "选择")
        if not arg.isdigit():
            yield event.plain_result("用法：/选择 <序号>")
            return
        pending = getattr(self, "_sts2_pending_choices", {}) or {}
        key = f"{event.unified_msg_origin}:{event.get_sender_id()}"
        state = pending.get(key)
        timeout = int(self._sts2_cfg("sts2_select_timeout_sec", 30) or 30)
        if not state or time.time() - float(state.get("created_at") or 0) > timeout:
            yield event.plain_result("没有可选择的尖塔查询结果，请重新查询。")
            return
        idx = int(arg) - 1
        items = state.get("items") or []
        if idx < 0 or idx >= len(items):
            yield event.plain_result(f"序号超出范围，请输入 1-{len(items)}。")
            return
        if "multi_items" in state:
            pending.pop(key, None)
            resolved_items = list(state.get("multi_items") or [])
            resolved_items.append(items[idx])
            remaining_queries = list(state.get("remaining_queries") or [])
            type_key = state.get("type_key")
            async for ret in self._sts2_continue_multi_query(
                event,
                resolved_items,
                remaining_queries,
                type_key,
            ):
                yield ret
            return
        async for ret in self._sts2_send_detail(event, items[idx]):
            yield ret

    @filter.command("尖塔刷新")
    async def sts2_refresh(self, event: AstrMessageEvent):
        if msg := self._sts2_guard_msg():
            yield event.plain_result(msg)
            return
        yield event.plain_result("正在刷新 Spire Codex 数据缓存，请稍候…")
        try:
            data = await self._sts2_client().fetch_all(force=True)
        except Exception as e:
            logger.error(f"[sts2_stats] 刷新失败: {e}", exc_info=True)
            yield event.plain_result(f"刷新失败：{e}")
            return
        counts = "，".join(f"{STS2_ENTITY_TYPES[k]['label']}{len(v)}" for k, v in data.items())
        yield event.plain_result(f"尖塔数据已刷新：{counts}")
