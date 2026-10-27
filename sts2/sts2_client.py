from __future__ import annotations

import asyncio
import re
import time
from difflib import SequenceMatcher
from typing import Any

import aiohttp
from astrbot.api import logger

from .paths import STS2_CACHE_FILE
from .utils import load_json, save_json

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

STS2_ENTITY_TYPES: dict[str, dict[str, str]] = {
    "cards": {"endpoint": "cards", "label": "卡牌"},
    "relics": {"endpoint": "relics", "label": "遗物"},
    "monsters": {"endpoint": "monsters", "label": "怪物"},
    "potions": {"endpoint": "potions", "label": "药水"},
    "events": {"endpoint": "events", "label": "事件"},
    "powers": {"endpoint": "powers", "label": "能力"},
    "characters": {"endpoint": "characters", "label": "角色"},
}

_STS2_TYPE_PRIORITY = {
    "cards": 0,
    "relics": 1,
    "monsters": 2,
    "events": 3,
    "potions": 4,
    "characters": 5,
    "powers": 9,
}


def strip_sts2_markup(text: object) -> str:
    """清理 Spire Codex 文本中的颜色/抖动等富文本标记。"""
    s = "" if text is None else str(text)
    s = re.sub(r"\[/?[a-zA-Z_]+(?:=[^\]]+)?\]", "", s)
    s = re.sub(r"\{([^}:]+)(?::[^}]+)?\}", r"\1", s)
    return s.replace("\r", "").strip()


def normalize_sts2_url(base_url: str, url: object) -> str:
    s = "" if url is None else str(url).strip()
    if not s:
        return ""
    if s.startswith(("http://", "https://")):
        return s
    root = base_url.split("/api", 1)[0].rstrip("/")
    return root + (s if s.startswith("/") else "/" + s)


def _normalize_query(text: object) -> str:
    return re.sub(r"\s+", "", str(text or "")).lower()


def _score(query: str, item: dict[str, Any]) -> float:
    q = _normalize_query(query)
    if not q:
        return 0.0
    fields = [
        item.get("name"),
        item.get("id"),
        item.get("description"),
        item.get("rarity"),
        item.get("type"),
        item.get("pool"),
    ]
    best = 0.0
    for raw in fields:
        t = _normalize_query(strip_sts2_markup(raw))
        if not t:
            continue
        if q == t:
            best = max(best, 1.0)
        elif q in t:
            best = max(best, 0.92 - min(len(t) - len(q), 20) * 0.01)
        else:
            best = max(best, SequenceMatcher(None, q, t).ratio())
    return best


def _type_priority(type_key: str) -> int:
    return _STS2_TYPE_PRIORITY.get(type_key, 50)


class SpireCodexClient:
    def __init__(
        self,
        *,
        base_url: str = "https://spire-codex.com/api",
        lang: str = "zhs",
        timeout: int = 15,
        ttl_hours: int = 12,
        rate_limit_per_min: int = 50,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.lang = lang
        self.timeout = max(3, int(timeout or 15))
        self.ttl_seconds = max(1, int(ttl_hours or 12)) * 3600
        self.min_interval = 60.0 / max(1, int(rate_limit_per_min or 50))
        self._session: aiohttp.ClientSession | None = None
        self._last_request = 0.0
        self._request_lock = asyncio.Lock()
        STS2_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        self._cache: dict[str, Any] = load_json(STS2_CACHE_FILE, {})

    def clear_cache(self) -> int:
        count = len(self._cache)
        self._cache.clear()
        save_json(STS2_CACHE_FILE, self._cache)
        return count

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.timeout),
                headers={"User-Agent": _UA, "Accept": "application/json"},
                trust_env=True,
            )
        return self._session

    async def _throttle(self) -> None:
        async with self._request_lock:
            now = time.monotonic()
            wait = self.min_interval - (now - self._last_request)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_request = time.monotonic()

    async def fetch_list(self, type_key: str, *, force: bool = False) -> list[dict[str, Any]]:
        meta = STS2_ENTITY_TYPES[type_key]
        now = time.time()
        cached = self._cache.get(type_key)
        if (
            not force
            and isinstance(cached, dict)
            and now - float(cached.get("fetched_at") or 0) < self.ttl_seconds
            and isinstance(cached.get("items"), list)
        ):
            return cached["items"]

        await self._throttle()
        session = await self._get_session()
        url = f"{self.base_url}/{meta['endpoint']}"
        async with session.get(url, params={"lang": self.lang}) as resp:
            resp.raise_for_status()
            data = await resp.json(content_type=None)

        items = data if isinstance(data, list) else data.get("value") or data.get("data") or []
        if not isinstance(items, list):
            items = []
        self._cache[type_key] = {"fetched_at": now, "items": items}
        save_json(STS2_CACHE_FILE, self._cache)
        return items

    async def get_json(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: float | None = None,
    ) -> Any:
        await self._throttle()
        session = await self._get_session()
        url = f"{self.base_url}/{path.lstrip('/')}"
        request_timeout = aiohttp.ClientTimeout(total=timeout) if timeout else None
        async with session.get(url, params=params or {}, timeout=request_timeout) as resp:
            resp.raise_for_status()
            return await resp.json(content_type=None)

    async def run_list_count(
        self,
        *,
        entity_type: str,
        entity_id: str,
        ascension: int = 10,
        win: bool | None = None,
    ) -> int:
        if entity_type == "cards":
            key = "card"
        elif entity_type == "relics":
            key = "relic"
        else:
            raise ValueError(f"unsupported winrate entity type: {entity_type}")
        params: dict[str, Any] = {
            key: entity_id,
            "ascension_min": ascension,
            "ascension_max": ascension,
            "limit": 1,
        }
        if win is not None:
            params["win"] = "true" if win else "false"
        data = await self.get_json("/runs/list", params)
        if isinstance(data, dict):
            return int(data.get("total") or 0)
        return 0

    async def community_stats(self, *, ascension: int = 10) -> dict[str, Any]:
        data = await self.get_json(
            "/runs/stats",
            {"ascension": str(ascension)},
            timeout=min(5.0, float(self.timeout)),
        )
        return data if isinstance(data, dict) else {}

    async def entity_stats(self, entity_type: str, entity_id: str) -> dict[str, Any]:
        now = time.time()
        cache_key = f"entity_stats:{entity_type}:{entity_id}"
        cached = self._cache.get(cache_key)
        stale_data = cached.get("data") if isinstance(cached, dict) and isinstance(cached.get("data"), dict) else None
        if (
            isinstance(cached, dict)
            and now - float(cached.get("fetched_at") or 0) < self.ttl_seconds
            and isinstance(cached.get("data"), dict)
        ):
            return cached["data"]
        try:
            data = await self.get_json(f"/runs/stats/{entity_type}/{entity_id}")
        except Exception:
            if stale_data is not None:
                logger.warning(f"[sts2_stats] using stale entity stats cache for {entity_type}/{entity_id}")
                return stale_data
            raise
        if not isinstance(data, dict):
            data = {}
        self._cache[cache_key] = {"fetched_at": now, "data": data}
        save_json(STS2_CACHE_FILE, self._cache)
        return data

    async def entity_scores(
        self,
        entity_type: str,
        *,
        character: str | None = None,
        stat_filter: str | None = None,
    ) -> dict[str, Any]:
        now = time.time()
        cache_key = f"entity_scores:{entity_type}:{character or ''}:{stat_filter or ''}"
        cached = self._cache.get(cache_key)
        stale_data = cached.get("data") if isinstance(cached, dict) and isinstance(cached.get("data"), dict) else None
        if (
            isinstance(cached, dict)
            and now - float(cached.get("fetched_at") or 0) < self.ttl_seconds
            and isinstance(cached.get("data"), dict)
        ):
            return cached["data"]
        params: dict[str, Any] = {}
        if character:
            params["character"] = character
        if stat_filter:
            params["stat_filter"] = stat_filter
        try:
            data = await self.get_json(f"/runs/scores/{entity_type}", params)
        except Exception:
            if stale_data is not None:
                logger.warning(f"[sts2_stats] using stale entity scores cache for {entity_type}/{stat_filter or 'all'}")
                return stale_data
            raise
        if not isinstance(data, dict):
            data = {}
        self._cache[cache_key] = {"fetched_at": now, "data": data}
        save_json(STS2_CACHE_FILE, self._cache)
        return data

    async def entity_metrics(
        self,
        entity_type: str,
        *,
        bracket: str = "a10",
        character: str | None = None,
    ) -> dict[str, Any]:
        now = time.time()
        cache_key = f"entity_metrics:{entity_type}:{bracket}:{character or ''}"
        cached = self._cache.get(cache_key)
        stale_data = cached.get("data") if isinstance(cached, dict) and isinstance(cached.get("data"), dict) else None
        if (
            isinstance(cached, dict)
            and now - float(cached.get("fetched_at") or 0) < self.ttl_seconds
            and isinstance(cached.get("data"), dict)
        ):
            return cached["data"]
        params: dict[str, Any] = {"bracket": bracket}
        if character:
            params["character"] = character
        try:
            data = await self.get_json(f"/runs/metrics/{entity_type}", params)
        except Exception:
            if stale_data is not None:
                logger.warning(
                    f"[sts2_stats] using stale entity metrics cache for {entity_type}/{bracket}/{character or 'all'}"
                )
                return stale_data
            raise
        if not isinstance(data, dict):
            data = {}
        self._cache[cache_key] = {"fetched_at": now, "data": data}
        save_json(STS2_CACHE_FILE, self._cache)
        return data

    async def entity_metric_map(
        self,
        entity_type: str,
        *,
        bracket: str = "a10",
        character: str | None = None,
    ) -> dict[str, dict[str, Any]]:
        data = await self.entity_metrics(entity_type, bracket=bracket, character=character)
        rows = data.get("rows") if isinstance(data, dict) else []
        if not isinstance(rows, list):
            return {}
        result: dict[str, dict[str, Any]] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            entity_id = str(row.get("id") or "")
            if entity_id:
                result[entity_id] = row
        return result

    async def entity_player_breakdown(
        self,
        entity_type: str,
        entity_id: str,
        *,
        ascension: int = 10,
    ) -> list[dict[str, Any]]:
        suffix = f"a{ascension}"
        brackets = [
            ("SOLO", f"solo:{suffix}"),
            ("P2", f"2p:{suffix}"),
        ]
        maps = await asyncio.gather(
            *(self.entity_metric_map(entity_type, bracket=bracket) for _, bracket in brackets),
            return_exceptions=True,
        )
        rows: list[dict[str, Any]] = []
        for (label, bracket), stat_map in zip(brackets, maps):
            if isinstance(stat_map, Exception):
                logger.warning(f"[sts2_stats] player breakdown failed for {entity_type}/{entity_id} {bracket}: {stat_map}")
                continue
            stat = stat_map.get(entity_id) if isinstance(stat_map, dict) else None
            if isinstance(stat, dict):
                copied = dict(stat)
                copied["label"] = label
                copied["bracket"] = bracket
                rows.append(copied)
            else:
                rows.append({"label": label, "bracket": bracket, "picks": 0, "wins": 0, "win_rate": None})
        return rows

    async def winrate_summary(
        self,
        *,
        entity_type: str,
        entity_id: str,
        ascension: int = 10,
    ) -> dict[str, Any]:
        bracket = f"a{ascension}"
        metric_raw, all_stats_raw = await asyncio.gather(
            self.entity_metrics(entity_type, bracket=bracket),
            self.entity_stats(entity_type, entity_id),
            return_exceptions=True,
        )
        metrics = metric_raw if isinstance(metric_raw, dict) else {}
        metric_rows = metrics.get("rows") if isinstance(metrics.get("rows"), list) else []
        metric_stats = next(
            (
                row
                for row in metric_rows
                if isinstance(row, dict) and str(row.get("id") or "") == entity_id
            ),
            {},
        )
        all_stats = all_stats_raw if isinstance(all_stats_raw, dict) else {}
        brackets = all_stats.get("brackets") if isinstance(all_stats.get("brackets"), dict) else {}
        bracket_stats = brackets.get(bracket) if isinstance(brackets.get(bracket), dict) else {}
        score_stats = bracket_stats or metric_stats

        player_breakdown: list[dict[str, Any]] = []
        suffix = f"a{ascension}"
        for label, player_bracket in (("SOLO", f"solo:{suffix}"), ("P2", f"2p:{suffix}")):
            stat = brackets.get(player_bracket)
            if not isinstance(stat, dict):
                continue
            copied = dict(stat)
            copied["label"] = label
            copied["bracket"] = player_bracket
            player_breakdown.append(copied)
        if not player_breakdown:
            try:
                player_breakdown = await self.entity_player_breakdown(
                    entity_type,
                    entity_id,
                    ascension=ascension,
                )
            except Exception as exc:
                logger.warning(f"[sts2_stats] player breakdown fallback failed for {entity_type}/{entity_id}: {exc}")

        errors = [
            type(value).__name__
            for value in (metric_raw, all_stats_raw)
            if isinstance(value, Exception)
        ]
        if errors:
            logger.warning(f"[sts2_stats] partial winrate data for {entity_type}/{entity_id}: {', '.join(errors)}")
        total = int(score_stats.get("picks") or 0)
        wins = int(score_stats.get("wins") or 0)
        try:
            win_rate = round(float(score_stats.get("win_rate")), 1)
        except (TypeError, ValueError):
            win_rate = round(wins / total * 100, 1) if total else None
        try:
            pick_rate = round(float(score_stats.get("pick_rate")), 2)
        except (TypeError, ValueError):
            pick_rate = None
        total_runs = int(metrics.get("total_runs") or 0)
        appearance_rate = pick_rate if pick_rate is not None else round(total / total_runs * 100, 2) if total and total_runs else None
        return {
            "entity_type": entity_type,
            "entity_id": entity_id,
            "ascension": ascension,
            "sample_runs": total,
            "wins": wins,
            "win_rate": win_rate,
            "score": score_stats.get("score"),
            "appearance_rate": appearance_rate,
            "community_total_runs": total_runs,
            "community_win_rate": metrics.get("baseline_win_rate"),
            "player_breakdown": player_breakdown,
            "all_ascension": all_stats,
        }

    async def fetch_all(self, *, force: bool = False) -> dict[str, list[dict[str, Any]]]:
        result: dict[str, list[dict[str, Any]]] = {}
        for type_key in STS2_ENTITY_TYPES:
            try:
                result[type_key] = await self.fetch_list(type_key, force=force)
            except Exception as e:
                logger.warning(f"[sts2_stats] fetch {type_key} failed: {e}")
                result[type_key] = []
        return result

    async def search(
        self,
        query: str,
        *,
        type_key: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        keys = [type_key] if type_key else list(STS2_ENTITY_TYPES.keys())
        hits: list[dict[str, Any]] = []
        for key in keys:
            if not key:
                continue
            items = await self.fetch_list(key)
            for item in items:
                if not isinstance(item, dict):
                    continue
                score = _score(query, item)
                if score >= 0.42:
                    copied = dict(item)
                    copied["_sts2_type"] = key
                    copied["_sts2_type_label"] = STS2_ENTITY_TYPES[key]["label"]
                    copied["_sts2_score"] = score
                    hits.append(copied)
        hits.sort(
            key=lambda x: (
                -float(x.get("_sts2_score") or 0),
                _type_priority(str(x.get("_sts2_type") or "")),
                str(x.get("name") or ""),
            )
        )
        return hits[:limit]
