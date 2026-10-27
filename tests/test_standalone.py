"""Offline integration checks; no AstrBot installation or network required."""
import importlib
import io
import json
import logging
from pathlib import Path
import sys
import tempfile
import time
import types
import unittest
from unittest.mock import AsyncMock, patch

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
pkg = types.ModuleType("standalone_plugin")
pkg.__path__ = [str(ROOT)]
sys.modules[pkg.__name__] = pkg
handlers = []


def command(*args, **kwargs):
    def decorate(func):
        handlers.append(func)
        return func
    return decorate


class Star:
    def __init__(self, context):
        self.context = context


for name in ("astrbot", "astrbot.api", "astrbot.api.event", "astrbot.api.star", "astrbot.api.message_components"):
    sys.modules[name] = types.ModuleType(name)
api = sys.modules["astrbot.api"]
api.logger = logging.getLogger("tests")
api.AstrBotConfig = dict
sys.modules["astrbot.api.event"].filter = types.SimpleNamespace(command=command, regex=command)
sys.modules["astrbot.api.event"].AstrMessageEvent = object
sys.modules["astrbot.api.star"].Star = Star
sys.modules["astrbot.api.star"].Context = object
main = importlib.import_module("standalone_plugin.main")
client_module = importlib.import_module("standalone_plugin.sts2.sts2_client")
images = importlib.import_module("standalone_plugin.sts2.sts2_images")
stats_images = importlib.import_module("standalone_plugin.sts2.sts2_stats_images")


class Event:
    unified_msg_origin = "group:test"
    message_str = ""

    def get_sender_id(self):
        return "user"

    def plain_result(self, text):
        return text


class StandaloneTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cache = Path(self.tmp.name) / "cache.json"
        p = patch.object(client_module, "STS2_CACHE_FILE", self.cache)
        p.start()
        self.addCleanup(p.stop)
        self.plugin = main.Sts2StatsPlugin(None, {})

    def test_entrypoint_owns_handlers(self):
        self.assertGreaterEqual(len(handlers), 16)
        self.assertTrue(all(h.__module__ == main.__name__ for h in handlers))
        self.assertIsInstance(self.plugin, Star)
        self.assertNotIn("matplotlib", sys.modules)

    async def test_config_and_lifecycle(self):
        self.plugin.config = {"SlaySpire": {"sts2_cache_ttl_hours": 3}}
        client = self.plugin._sts2_client()
        self.assertEqual(client.ttl_seconds, 10800)
        session = await client._get_session()
        self.plugin._sts2_pending_choices["test"] = {}
        await self.plugin.terminate()
        self.assertTrue(session.closed)
        self.assertFalse(self.plugin._sts2_pending_choices)
        self.assertEqual(main.DATA_DIR.name, "astrbot_plugin_sts2_stats")

    async def test_default_cache_and_search_priority(self):
        client = self.plugin._sts2_client()
        self.assertEqual(client.ttl_seconds, 120 * 3600)
        client.fetch_list = AsyncMock(side_effect=lambda key: [{"id": "ANGER", "name": "愤怒"}] if key in {"cards", "powers"} else [])
        item, candidates, _ = await self.plugin._sts2_resolve_one_query("愤怒", None)
        self.assertEqual(item["_sts2_type"], "cards")
        self.assertEqual(candidates, [])

    async def test_alias_preserves_all_arguments(self):
        event = Event()
        event.message_str = "/尖塔搜索 愤怒 打击"
        captured = []
        async def query(event, arg, type_key):
            captured.append(arg)
            yield "ok"
        self.plugin._sts2_query_common = query
        self.assertEqual([r async for r in self.plugin.sts2_query(event, "愤怒")], ["ok"])
        self.assertEqual(captured, ["愤怒 打击"])

    async def test_disabled_shortcut(self):
        self.plugin.config = {"sts2_enabled": False}
        results = [r async for r in self.plugin.sts2_anger(Event())]
        self.assertIn("未启用", results[0])

    async def test_choice_isolation_and_expiration(self):
        self.plugin._sts2_pending_choices["group:test:someone_else"] = {"created_at": time.time(), "items": [{}]}
        results = [r async for r in self.plugin.sts2_select(Event(), "1")]
        self.assertIn("没有可选择", results[0])
        self.plugin._sts2_pending_choices["group:test:user"] = {"created_at": time.time() - 60, "items": [{}]}
        results = [r async for r in self.plugin.sts2_select(Event(), "1")]
        self.assertIn("没有可选择", results[0])

    async def test_cached_statistics_survive_outage(self):
        client = self.plugin._sts2_client()
        client._cache["entity_metrics:cards:solo:a10:IRONCLAD"] = {"fetched_at": 1, "data": {"rows": [{"id": "ANGER", "win_rate": 50}]}}
        client.get_json = AsyncMock(side_effect=TimeoutError())
        data = await client.entity_metric_map("cards", bracket="solo:a10", character="IRONCLAD")
        self.assertEqual(data["ANGER"]["win_rate"], 50)
        client.clear_cache()
        self.assertEqual(json.loads(self.cache.read_text()), {})

    async def test_partial_winrate_response(self):
        client = self.plugin._sts2_client()
        client.entity_metrics = AsyncMock(return_value={"total_runs": 100, "rows": [{"id": "ANGER", "picks": 20, "wins": 5}]})
        client.entity_stats = AsyncMock(side_effect=TimeoutError())
        client.entity_player_breakdown = AsyncMock(return_value=[])
        result = await client.winrate_summary(entity_type="cards", entity_id="ANGER")
        self.assertEqual(result["win_rate"], 25)
        self.assertEqual(result["appearance_rate"], 20)

    def test_renderers(self):
        item = {"id": "ANGER", "name": "愤怒", "description": "造成 6 点伤害。", "cost": 0, "type": "攻击"}
        outputs = [images.render_sts2_overview(), images.render_sts2_detail(item, "cards"), stats_images.render_sts2_winrate(item=item, type_label="卡牌", stats={"ascension": 10, "sample_runs": 100, "wins": 50, "win_rate": 50}), stats_images.render_sts2_card_power_table(title="从夯到拉", character_label="战士", rows=[{"name": "愤怒", "win_rate": 50, "picks": 100}], ascension_label="A10")]
        for png in outputs:
            with Image.open(io.BytesIO(png)) as image:
                image.verify()
        preview = ROOT / "test-output"
        preview.mkdir(exist_ok=True)
        (preview / "overview.png").write_bytes(outputs[0])
        (preview / "detail.png").write_bytes(outputs[1])


if __name__ == "__main__":
    unittest.main()
