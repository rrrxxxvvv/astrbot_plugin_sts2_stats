from __future__ import annotations

import io
from typing import Any

from PIL import Image, ImageDraw

from .image_utils import _load_font, _open_icon, _truncate_text, _wrap_text
from .sts2_client import STS2_ENTITY_TYPES, strip_sts2_markup

W = 1080
PAD = 30
BG = (18, 20, 28)
BG_HDR = (28, 32, 48)
BG_ROW = (23, 26, 38)
BG_CARD = (31, 36, 54)
TEXT = (224, 229, 240)
SUB = (155, 164, 184)
DIM = (96, 106, 130)
SEP = (48, 55, 78)
ACCENT = (190, 146, 72)

RARITY_COLORS = {
    "Basic": (130, 136, 148),
    "Common": (214, 218, 225),
    "Uncommon": (96, 150, 224),
    "Rare": (225, 175, 72),
    "Ancient": (190, 115, 220),
    "Boss": (230, 100, 80),
    "Special": (130, 210, 150),
}


def _buf(img: Image.Image) -> bytes:
    out = io.BytesIO()
    img.save(out, format="PNG", optimize=True)
    return out.getvalue()


def _fit_image(
    icon_bytes: bytes | None,
    max_w: int,
    max_h: int,
) -> Image.Image:
    if not icon_bytes:
        return Image.new("RGBA", (max_w, max_h), (52, 58, 76, 255))
    try:
        src = Image.open(io.BytesIO(icon_bytes)).convert("RGBA")
        src.thumbnail((max_w, max_h), Image.Resampling.LANCZOS)
        canvas = Image.new("RGBA", (max_w, max_h), (0, 0, 0, 0))
        canvas.paste(src, ((max_w - src.width) // 2, (max_h - src.height) // 2), src)
        return canvas
    except Exception:
        return Image.new("RGBA", (max_w, max_h), (65, 72, 92, 255))


def _badge(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    text: str,
    color: tuple[int, int, int],
    font,
) -> int:
    text = text or "—"
    tw = int(draw.textlength(text, font=font))
    h = font.size + 12
    w = tw + 22
    draw.rounded_rectangle([(x, y), (x + w, y + h)], radius=6, fill=color)
    draw.text((x + 11, y + 5), text, fill=(18, 20, 28), font=font)
    return w


def _header(draw: ImageDraw.ImageDraw, title: str, subtitle: str = "") -> int:
    f_t = _load_font(34)
    f_s = _load_font(19)
    h = 92
    draw.rectangle([(0, 0), (W, h)], fill=BG_HDR)
    draw.rectangle([(0, 0), (7, h)], fill=ACCENT)
    draw.text((PAD, 14), _truncate_text(draw, title, f_t, W - PAD * 2), fill=TEXT, font=f_t)
    if subtitle:
        draw.text((PAD, 56), _truncate_text(draw, subtitle, f_s, W - PAD * 2), fill=SUB, font=f_s)
    draw.line([(0, h - 1), (W, h - 1)], fill=SEP)
    return h


def _footer(draw: ImageDraw.ImageDraw, y: int, text: str) -> None:
    f = _load_font(17)
    draw.rectangle([(0, y), (W, y + 42)], fill=BG_HDR)
    if text:
        draw.text((PAD, y + 11), text, fill=DIM, font=f)
    draw.rectangle([(0, 0), (W - 1, y + 41)], outline=SEP, width=2)


def _draw_icon(img: Image.Image, icon_bytes: bytes | None, x: int, y: int, size: int) -> None:
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([(x - 4, y - 4), (x + size + 4, y + size + 4)], radius=8, fill=(36, 41, 58))
    icon = _open_icon(icon_bytes, size)
    img.paste(icon, (x, y), icon)


def _draw_art(
    img: Image.Image,
    icon_bytes: bytes | None,
    x: int,
    y: int,
    max_w: int,
    max_h: int,
) -> None:
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle(
        [(x - 6, y - 6), (x + max_w + 6, y + max_h + 6)],
        radius=10,
        fill=(36, 41, 58),
    )
    art = _fit_image(icon_bytes, max_w, max_h)
    img.paste(art, (x, y), art)


def _format_meta(item: dict[str, Any], type_key: str) -> list[str]:
    if type_key == "cards":
        cost = item.get("cost")
        if item.get("is_x_cost"):
            cost = "X"
        bits = [f"费用 {cost if cost is not None else '—'}", item.get("type"), item.get("rarity"), item.get("color")]
        vals = []
        for label, key in (("伤害", "damage"), ("格挡", "block"), ("次数", "hit_count"), ("抽牌", "cards_draw"), ("能量", "energy_gain")):
            if item.get(key) is not None:
                vals.append(f"{label} {item.get(key)}")
        return [" · ".join(str(x) for x in bits if x), " · ".join(vals)]
    if type_key in {"relics", "potions"}:
        return [" · ".join(str(x) for x in (item.get("rarity"), item.get("pool")) if x)]
    if type_key == "monsters":
        hp = f"生命 {item.get('min_hp') or '—'}"
        if item.get("max_hp"):
            hp += f"-{item.get('max_hp')}"
        hp_a = ""
        if item.get("min_hp_ascension"):
            hp_a = f"进阶 {item.get('min_hp_ascension')}"
            if item.get("max_hp_ascension"):
                hp_a += f"-{item.get('max_hp_ascension')}"
        return [" · ".join(str(x) for x in (item.get("type"), hp, hp_a) if x)]
    if type_key == "events":
        return [" · ".join(str(x) for x in (item.get("type"), item.get("act"), item.get("epithet")) if x)]
    if type_key == "powers":
        return [" · ".join(str(x) for x in (item.get("type"), item.get("stack_type")) if x)]
    if type_key == "characters":
        return [
            f"生命 {item.get('starting_hp', '—')} · 金币 {item.get('starting_gold', '—')} · 能量 {item.get('max_energy', '—')}",
            "初始遗物：" + "、".join(item.get("starting_relics") or []) if item.get("starting_relics") else "",
        ]
    return []


def _description(item: dict[str, Any], type_key: str) -> str:
    if type_key == "monsters":
        moves = item.get("moves") or []
        if isinstance(moves, list) and moves:
            lines = []
            pattern = _monster_attack_pattern(item, moves)
            if pattern:
                lines.append(f"行动模式：{pattern}")
            for m in moves[:10]:
                if not isinstance(m, dict):
                    lines.append(str(m))
                    continue
                name = str(m.get("name") or m.get("id") or "未知行动")
                parts = []
                intent = m.get("intent")
                if intent:
                    parts.append(f"意图 {intent}")
                damage = m.get("damage") or {}
                if isinstance(damage, dict) and (damage.get("normal") is not None or damage.get("ascension") is not None):
                    dmg = f"伤害 {damage.get('normal', '—')}"
                    if damage.get("ascension") is not None:
                        dmg += f"/进阶 {damage.get('ascension')}"
                    if damage.get("hit_count"):
                        dmg += f" x{damage.get('hit_count')}"
                    parts.append(dmg)
                if m.get("block") is not None:
                    parts.append(f"格挡 {m.get('block')}")
                if m.get("heal") is not None:
                    parts.append(f"治疗 {m.get('heal')}")
                powers = m.get("powers") or []
                if isinstance(powers, list) and powers:
                    power_bits = []
                    for p in powers[:3]:
                        if isinstance(p, dict):
                            pid = p.get("id") or p.get("power") or p.get("name") or "能力"
                            amount = p.get("amount") or p.get("stacks")
                            target = p.get("target")
                            power_bits.append(f"{pid}{amount if amount is not None else ''}{'→' + str(target) if target else ''}")
                        else:
                            power_bits.append(str(p))
                    parts.append("能力 " + "、".join(power_bits))
                detail = " · ".join(parts) if parts else "暂无数值"
                lines.append(f"{name}：{detail}")
            return "\n".join(lines)
        return "暂无技能轮转数据。"
    if type_key == "characters":
        deck = item.get("starting_deck") or []
        suffix = "\n初始牌组：" + "、".join(deck[:12]) if deck else ""
        return strip_sts2_markup(item.get("description")) + suffix
    text = item.get("description") or item.get("flavor") or item.get("dialogue") or ""
    if isinstance(text, list):
        text = " / ".join(str(x) for x in text[:6])
    return strip_sts2_markup(text) or "暂无描述。"


def _monster_attack_pattern(item: dict[str, Any], moves: list[Any]) -> str:
    raw = item.get("attack_pattern")
    if isinstance(raw, dict):
        text = raw.get("description") or raw.get("pattern") or raw.get("name")
        if text:
            return _normalize_monster_pattern_text(text)
    elif isinstance(raw, list):
        names = []
        move_names = {
            str(m.get("id") or ""): str(m.get("name") or m.get("id") or "")
            for m in moves
            if isinstance(m, dict)
        }
        for entry in raw:
            if isinstance(entry, dict):
                text = entry.get("description") or entry.get("name") or move_names.get(str(entry.get("id") or ""))
            else:
                text = move_names.get(str(entry), entry)
            if text:
                names.append(str(text))
        if names:
            return _normalize_monster_pattern_text("->".join(names))
    else:
        text = strip_sts2_markup(raw)
        if text and not all(key in text for key in ("'type'", "'id'", "'description'")):
            return _normalize_monster_pattern_text(text)

    description = item.get("description")
    if isinstance(description, str) and "repeat" in description.lower():
        return _normalize_monster_pattern_text(description)
    return ""


def _normalize_monster_pattern_text(text: object) -> str:
    s = strip_sts2_markup(text)
    s = s.replace("->", "→").replace("⇒", "→")
    s = "→".join(part.strip() for part in s.split("→") if part.strip())
    return s.replace("→", "->")


def _apply_upgrade_value(base: object, upgrade_value: object) -> object:
    if isinstance(base, (int, float)):
        if isinstance(upgrade_value, str):
            s = upgrade_value.strip()
            if s.startswith(("+", "-")):
                try:
                    return base + int(s)
                except ValueError:
                    try:
                        return base + float(s)
                    except ValueError:
                        return upgrade_value
        return upgrade_value
    return upgrade_value


def _upgrade_summary(item: dict[str, Any]) -> str:
    upgrade = item.get("upgrade") or {}
    if not isinstance(upgrade, dict) or not upgrade:
        return ""
    labels = {
        "cost": "费用",
        "damage": "伤害",
        "block": "格挡",
        "hit_count": "次数",
        "cards_draw": "抽牌",
        "energy_gain": "能量",
        "hp_loss": "失去生命",
        "star_cost": "星费",
    }
    parts: list[str] = []
    for key, value in upgrade.items():
        if isinstance(value, (dict, list)):
            continue
        label = labels.get(key, key)
        base = item.get(key)
        upgraded = _apply_upgrade_value(base, value)
        if base is None:
            parts.append(f"{label}：{value}")
        else:
            parts.append(f"{label}：{base} → {upgraded}")
    return "；".join(parts)


def _upgrade_description(item: dict[str, Any]) -> str:
    upgraded = strip_sts2_markup(item.get("upgrade_description"))
    summary = _upgrade_summary(item)
    if upgraded and summary:
        return f"{upgraded}\n{summary}"
    return upgraded or summary


def _winrate_lines(item: dict[str, Any]) -> list[str]:
    if item.get("_sts2_winrate_error"):
        return ["胜率接口暂不可用；卡牌/遗物基础信息来自本地缓存。"]
    stats = item.get("_sts2_winrate")
    if not isinstance(stats, dict):
        return []
    def pct(v: object) -> str:
        try:
            return f"{float(v):.1f}%"
        except (TypeError, ValueError):
            return "暂无"
    def num(v: object) -> str:
        try:
            return f"{int(v):,}"
        except (TypeError, ValueError):
            return "0"
    all_stats = stats.get("all_ascension") or {}
    has_ascension = stats.get("win_rate") is not None or int(stats.get("sample_runs") or 0) > 0
    has_all = all_stats.get("win_rate") is not None or all_stats.get("score") is not None
    breakdown = stats.get("player_breakdown") or []
    has_breakdown = isinstance(breakdown, list) and any(
        isinstance(row, dict)
        and str(row.get("label") or "") in {"SOLO", "P2"}
        and (row.get("win_rate") is not None or int(row.get("picks") or 0) > 0)
        for row in breakdown
    )
    if not has_ascension and not has_all and not has_breakdown:
        return []

    lines: list[str] = []
    if has_ascension:
        lines.append(
            f"A{stats.get('ascension', 10)} 胜率：{pct(stats.get('win_rate'))}（{num(stats.get('wins'))}/{num(stats.get('sample_runs'))}）"
        )
        lines.append(
            f"A{stats.get('ascension', 10)} 评分：{stats.get('score', '暂无')} · 出现率：{pct(stats.get('appearance_rate'))}"
        )
    if isinstance(breakdown, list):
        for row in breakdown:
            if not isinstance(row, dict):
                continue
            label = str(row.get("label") or "")
            if label not in {"SOLO", "P2"}:
                continue
            picks = int(row.get("picks") or 0)
            if not label or picks <= 0:
                continue
            lines.append(
                f"A{stats.get('ascension', 10)} {label}："
                f"胜率 {pct(row.get('win_rate'))} · 选取 {pct(row.get('pick_rate'))} · 样本 {num(picks)}"
            )
    if has_all:
        lines.append(
            f"全难度评分：{all_stats.get('score', '暂无')} · 全难度胜率：{pct(all_stats.get('win_rate'))}"
        )
    return lines


def render_sts2_detail(item: dict[str, Any], type_key: str, icon_bytes: bytes | None = None) -> bytes:
    type_label = STS2_ENTITY_TYPES.get(type_key, {}).get("label", type_key)
    name = str(item.get("name") or item.get("id") or "未知条目")
    f_s = _load_font(20)
    f_m = _load_font(24)
    f_b = _load_font(28)
    f_section = _load_font(22)

    tmp = Image.new("RGB", (1, 1))
    td = ImageDraw.Draw(tmp)
    art_w = 330 if type_key == "cards" else 210
    art_h = 462 if type_key == "cards" else 210
    text_x = PAD + art_w + 42
    text_w = W - text_x - PAD
    desc_width = text_w if type_key == "cards" else W - PAD * 2
    desc_lines = _wrap_text(td, _description(item, type_key), f_m, desc_width)
    meta_lines = [x for x in _format_meta(item, type_key) if x]
    winrate_lines = _winrate_lines(item)
    upgrade = _upgrade_description(item)
    upgrade_lines = _wrap_text(td, upgrade, f_s, W - PAD * 2) if upgrade else []
    header_h = 92
    art_y = header_h + 28
    art_bottom = art_y + art_h + 6

    # First pass: compute the text bottom so the footer never overlaps art.
    by = header_h + 30
    by += 44  # badges
    by += 42  # title
    by += 30 * min(len(meta_lines), 3)
    y = max(by + 14, header_h + 190)
    if type_key != "cards":
        y = art_y + art_h + 30
    y += 20 + 34
    y += len(desc_lines) * 34
    if winrate_lines:
        y += 18 + 34 + len(winrate_lines) * 27
    if upgrade_lines:
        y += 18 + 34 + len(upgrade_lines) * 27
    keywords = item.get("keywords") or []
    if isinstance(keywords, list) and keywords:
        y += 14 + 28
    footer_y = max(y + 20, art_bottom + 24)
    h = footer_y + 42

    img = Image.new("RGB", (W, h), BG)
    draw = ImageDraw.Draw(img)
    y = _header(draw, name, f"尖塔{type_label} · {item.get('id') or ''}")

    if type_key == "cards":
        _draw_art(img, icon_bytes, PAD, art_y, art_w, art_h)
    else:
        _draw_icon(img, icon_bytes, PAD, art_y, art_w)
    x = text_x
    by = y + 30
    rarity_key = str(item.get("rarity_key") or item.get("type") or "")
    _badge(draw, x, by, type_label, ACCENT, f_s)
    if item.get("rarity") or rarity_key:
        color = RARITY_COLORS.get(rarity_key, (100, 145, 210))
        _badge(draw, x + 88, by, str(item.get("rarity") or rarity_key), color, f_s)
    by += 44
    draw.text((x, by), _truncate_text(draw, name, f_b, W - x - PAD), fill=TEXT, font=f_b)
    by += 42
    for line in meta_lines[:3]:
        draw.text((x, by), _truncate_text(draw, line, f_s, W - x - PAD), fill=SUB, font=f_s)
        by += 30

    y = max(by + 14, y + 190)
    if type_key == "cards":
        y = y + 4
    else:
        y = art_y + art_w + 30
    draw.line([(text_x if type_key == "cards" else PAD, y), (W - PAD, y)], fill=SEP)
    y += 20
    draw.text((text_x if type_key == "cards" else PAD, y), "普通效果", fill=ACCENT, font=f_section)
    y += 34
    desc_x = text_x if type_key == "cards" else PAD
    for line in desc_lines:
        draw.text((desc_x, y), line, fill=TEXT, font=f_m)
        y += 34
    if winrate_lines:
        y += 18
        draw.text((desc_x, y), "社区胜率", fill=ACCENT, font=f_section)
        y += 34
        for line in winrate_lines:
            draw.text((desc_x, y), _truncate_text(draw, line, f_s, W - desc_x - PAD), fill=SUB, font=f_s)
            y += 27
    if upgrade_lines:
        y += 18
        draw.text((desc_x, y), "强化后", fill=ACCENT, font=f_section)
        y += 34
        for line in upgrade_lines:
            draw.text((desc_x, y), line, fill=SUB, font=f_s)
            y += 27

    if isinstance(keywords, list) and keywords:
        y += 14
        draw.text((desc_x, y), "关键词：" + " / ".join(str(x) for x in keywords[:8]), fill=DIM, font=f_s)
        y += 28

    _footer(draw, max(y + 20, art_bottom + 24), "数据来源：Spire Codex")
    return _buf(img)


def render_sts2_detail_bundle(images: list[bytes]) -> bytes:
    opened: list[Image.Image] = []
    for data in images:
        try:
            opened.append(Image.open(io.BytesIO(data)).convert("RGB"))
        except Exception:
            continue
    if not opened:
        return _buf(Image.new("RGB", (W, 120), BG))
    gap = 10
    width = max(img.width for img in opened)
    height = sum(img.height for img in opened) + gap * (len(opened) - 1)
    out = Image.new("RGB", (width, height), BG)
    y = 0
    for img in opened:
        out.paste(img, ((width - img.width) // 2, y))
        y += img.height + gap
    return _buf(out)


def render_sts2_list(
    items: list[dict[str, Any]],
    query: str,
    total: int,
    icon_map: dict[str, bytes | None] | None = None,
) -> bytes:
    f_t = _load_font(22)
    f_b = _load_font(22)
    f_s = _load_font(18)
    f_xs = _load_font(17)
    row_h = 132
    icon_w = 76
    icon_h = 106
    h = 62 + len(items) * row_h + 44
    img = Image.new("RGB", (W, h), BG)
    draw = ImageDraw.Draw(img)
    y0 = _header(draw, f"尖塔查询结果 · {query}", f"共 {total} 条，显示前 {len(items)} 条")
    for idx, item in enumerate(items, 1):
        y = y0 + (idx - 1) * row_h
        draw.rectangle([(0, y), (W, y + row_h)], fill=BG if idx % 2 else BG_ROW)
        type_label = item.get("_sts2_type_label") or ""
        type_key = item.get("_sts2_type") or ""
        score = int(float(item.get("_sts2_score") or 0) * 100)
        draw.text((PAD, y + 34), f"{idx}.", fill=DIM, font=f_b)

        ix = PAD + 44
        _draw_art(img, (icon_map or {}).get(str(idx - 1)), ix, y + 13, icon_w, icon_h)

        x = ix + icon_w + 24
        _badge(draw, x, y + 10, str(type_label), (82, 126, 196), f_s)
        x += 82
        name = str(item.get("name") or item.get("id") or "")
        draw.text((x, y + 10), _truncate_text(draw, name, f_b, W - x - 90), fill=TEXT, font=f_b)
        sub = " · ".join(str(v) for v in (item.get("rarity"), item.get("type"), item.get("pool")) if v)
        if sub:
            draw.text((x, y + 42), _truncate_text(draw, sub, f_s, W - x - 90), fill=SUB, font=f_s)
        desc = _description(item, str(type_key))
        desc = " ".join(desc.split())
        draw.text((x, y + 74), _truncate_text(draw, desc, f_xs, W - x - PAD), fill=DIM, font=f_xs)
        draw.text((W - PAD - 58, y + 21), f"{score}", fill=DIM, font=f_s)
        draw.line([(PAD, y + row_h - 1), (W - PAD, y + row_h - 1)], fill=SEP)
    _footer(draw, y0 + len(items) * row_h + 6, "发送 /选择 <序号> 查看详情")
    return _buf(img)


def render_sts2_overview() -> bytes:
    commands = [
        ("/尖塔查询 <关键词>", "跨卡牌、遗物、怪物、药水、事件、能力、角色搜索"),
        ("/尖塔卡牌 <名称>", "查询卡牌详情"),
        ("/尖塔遗物 <名称>", "查询遗物详情"),
        ("/尖塔怪物 <名称>", "查询怪物详情"),
        ("/尖塔药水 <名称>", "查询药水详情"),
        ("/尖塔事件 <名称>", "查询事件详情"),
        ("/尖塔能力 <名称>", "查询能力详情"),
        ("/尖塔角色 <名称>", "查询角色初始信息"),
        ("/尖塔胜率 <卡/遗物>", "查询社区胜率、样本与单人/双人统计，默认 A10"),
        ("/从夯到拉 <范围>", "胜率降序：角色、通用、无色、诅咒、多人、遗物或先古来源"),
        ("/从拉到夯 <范围>", "按胜率从低到高生成排行图，范围同上"),
        ("/尖塔选择 <序号>", "选择候选，别名 /选择；批量查询最多 6 项，以空格或逗号分隔"),
        ("/尖塔刷新", "强制刷新 Spire Codex 本地缓存"),
        ("/尖塔 reset", "清空数据缓存与选择状态，保留卡图缓存"),
    ]
    row_h = 38
    h = 92 + len(commands) * row_h + 50
    img = Image.new("RGB", (W, h), BG)
    draw = ImageDraw.Draw(img)
    y = _header(draw, "尖塔查询", "Slay the Spire 2 · Spire Codex")
    f_cmd = _load_font(16)
    f_desc = _load_font(13)
    for i, (cmd, desc) in enumerate(commands):
        yy = y + i * row_h
        draw.rectangle([(0, yy), (W, yy + row_h)], fill=BG if i % 2 == 0 else BG_ROW)
        draw.text((PAD, yy + 9), cmd, fill=ACCENT, font=f_cmd)
        draw.text((PAD + 220, yy + 11), _truncate_text(draw, desc, f_desc, W - PAD * 2 - 220), fill=SUB, font=f_desc)
    _footer(draw, y + len(commands) * row_h + 8, "数据来源：Spire Codex · 使用本地缓存 · 社区样本仅供参考")
    return _buf(img)
