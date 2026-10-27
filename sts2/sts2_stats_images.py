from __future__ import annotations

import io
from typing import Any

from PIL import Image, ImageDraw

from .image_utils import _load_font, _open_icon, _truncate_text

W = 900
PAD = 28
BG = (18, 20, 28)
BG_HDR = (28, 32, 48)
ROW = (24, 28, 42)
TEXT = (225, 230, 242)
SUB = (156, 166, 188)
DIM = (100, 110, 135)
ACCENT = (214, 166, 76)
SEP = (48, 55, 78)
RANK_BAR = (91, 126, 171)


def _buf(img: Image.Image) -> bytes:
    out = io.BytesIO()
    img.save(out, format="PNG", optimize=True)
    return out.getvalue()


def _fmt_pct(value: object) -> str:
    if value is None:
        return "暂无"
    try:
        return f"{float(value):.1f}%"
    except (TypeError, ValueError):
        return str(value)


def _fmt_pick_rate(value: object) -> str:
    if value is None:
        return "选取 --"
    return f"选取 {_fmt_pct(value)}"


def _fmt_int(value: object) -> str:
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return "0"


def _fmt_compact_int(value: object) -> str:
    try:
        num = int(value)
    except (TypeError, ValueError):
        return "0"
    if num >= 1_000_000:
        return f"{num / 1_000_000:.1f}m"
    if num >= 100_000:
        return f"{num // 1000}k"
    if num >= 10_000:
        return f"{num / 1000:.1f}k"
    return f"{num:,}"


def _tier(score: object) -> str:
    try:
        s = float(score)
    except (TypeError, ValueError):
        return "?"
    if s >= 90:
        return "S"
    if s >= 75:
        return "A"
    if s >= 60:
        return "B"
    if s >= 45:
        return "C"
    if s >= 30:
        return "D"
    return "F"


def _row_name_color(row: dict[str, Any]) -> tuple[int, int, int]:
    value = row.get("name_color")
    if isinstance(value, (list, tuple)) and len(value) == 3:
        try:
            return tuple(max(0, min(255, int(v))) for v in value)
        except (TypeError, ValueError):
            pass
    return TEXT


def _draw_rank_bar(
    draw: ImageDraw.ImageDraw,
    x0: int,
    y0: int,
    width: int,
    y1: int,
    card_type: object,
) -> None:
    if width <= 0 or y1 <= y0:
        return
    kind = str(card_type or "").lower()
    x1 = x0 + width
    height = y1 - y0
    if kind == "attack":
        tip = min(9, max(4, width // 4))
        points = [(x0, y0), (x1 - tip, y0), (x1, y0 + height // 2), (x1 - tip, y1), (x0, y1)]
        draw.line(
            points + [points[0]],
            fill=RANK_BAR,
            width=2,
            joint="curve",
        )
    elif kind == "skill":
        draw.rectangle([(x0, y0), (x1, y1)], outline=RANK_BAR, width=2)
    elif kind == "power":
        radius = max(3, height // 2)
        cap_left = max(x0, x1 - height)
        cap_center_x = max(x0, x1 - radius)
        draw.line([(x0, y0), (cap_center_x, y0)], fill=RANK_BAR, width=2)
        draw.arc([(cap_left, y0), (x1, y1)], start=-90, end=90, fill=RANK_BAR, width=2)
        draw.line([(cap_center_x, y1), (x0, y1), (x0, y0)], fill=RANK_BAR, width=2)
    elif kind in {"unframed", "curse", "status", "event"}:
        mid_y = (y0 + y1) // 2
        draw.rounded_rectangle([(x0, mid_y - 2), (x1, mid_y + 2)], radius=2, fill=RANK_BAR)
    elif card_type:
        draw.polygon(
            [(x0, y0), (x1, y0), (x1, y1), (x0, y1)],
            fill=RANK_BAR,
        )
    else:
        draw.rounded_rectangle([(x0, y0), (x1, y1)], radius=max(3, height // 2), fill=RANK_BAR)


def render_sts2_winrate(
    *,
    item: dict[str, Any],
    type_label: str,
    stats: dict[str, Any],
) -> bytes:
    f_t = _load_font(30)
    f_b = _load_font(24)
    f_m = _load_font(20)
    f_s = _load_font(17)
    all_stats = stats.get("all_ascension") or {}
    rows = [
        ("A10 样本", _fmt_int(stats.get("sample_runs")), "包含该条目的 A10 对局数"),
        ("A10 胜率", _fmt_pct(stats.get("win_rate")), f"胜局 {_fmt_int(stats.get('wins'))}"),
        ("A10 评分", f"{stats.get('score', '暂无')} / {_tier(stats.get('score'))}", "Codex Score · A10"),
        ("A10 出现率", _fmt_pct(stats.get("appearance_rate")), f"总 A10 对局 {_fmt_int(stats.get('community_total_runs'))}"),
        ("全难度评分", f"{all_stats.get('score', '暂无')} / {_tier(all_stats.get('score'))}", f"全难度胜率 {_fmt_pct(all_stats.get('win_rate'))}"),
    ]
    for row in stats.get("player_breakdown") or []:
        if not isinstance(row, dict):
            continue
        label = str(row.get("label") or "")
        if label not in {"SOLO", "P2"}:
            continue
        rows.append((
            f"A10 {label}",
            _fmt_pct(row.get("win_rate")),
            f"{_fmt_int(row.get('wins'))}/{_fmt_int(row.get('picks'))} · 选取 {_fmt_pct(row.get('pick_rate'))}",
        ))
    h = 140 + len(rows) * 38 + 34
    img = Image.new("RGB", (W, h), BG)
    draw = ImageDraw.Draw(img)

    draw.rectangle([(0, 0), (W, 86)], fill=BG_HDR)
    draw.rectangle([(0, 0), (7, 86)], fill=ACCENT)
    name = str(item.get("name") or item.get("id") or "未知条目")
    draw.text((PAD, 12), _truncate_text(draw, name, f_t, W - PAD * 2), fill=TEXT, font=f_t)
    draw.text(
        (PAD, 52),
        f"尖塔{type_label}胜率 · 默认 A{stats.get('ascension', 10)}",
        fill=SUB,
        font=f_s,
    )

    y = 104
    label_w = 150
    for i, (label, value, note) in enumerate(rows):
        draw.rectangle([(0, y), (W, y + 38)], fill=BG if i % 2 == 0 else ROW)
        draw.text((PAD, y + 8), label, fill=SUB, font=f_s)
        draw.text((PAD + label_w, y + 5), value, fill=TEXT if i != 1 else ACCENT, font=f_b)
        draw.text((PAD + 360, y + 10), _truncate_text(draw, note, f_s, W - PAD - 360), fill=DIM, font=f_s)
        draw.line([(PAD, y + 37), (W - PAD, y + 37)], fill=SEP)
        y += 38

    draw.rectangle([(0, h - 34), (W, h)], fill=BG_HDR)
    draw.text((PAD, h - 25), "数据来源：Spire Codex runs/metrics；玩家数使用 solo:a10/2p:a10", fill=DIM, font=f_s)
    draw.rectangle([(0, 0), (W - 1, h - 1)], outline=SEP, width=2)
    return _buf(img)


def render_sts2_card_power_table(
    *,
    title: str = "从夯到拉",
    character_label: str,
    rows: list[dict[str, Any]],
    ascension_label: str = "全难度",
    subtitle: str = "角色卡牌胜率排行",
    footnote: str = "数据来源：Spire Codex runs/metrics；按当前 bracket 统计",
    title_icon: bytes | None = None,
) -> bytes:
    has_icons = any(row.get("icon") for row in rows)
    has_card_types = any(row.get("card_type") for row in rows)
    compact = len(rows) > 40
    relic_grid = has_icons and compact
    canvas_w = 1400 if relic_grid else 1180 if compact else W
    f_t = _load_font(30)
    f_b = _load_font(18 if compact else 21)
    f_m = _load_font(15 if compact else 18)
    f_s = _load_font(13 if compact else 15)
    row_h = 31 if compact else 42
    header_h = 138 if has_card_types else 116
    foot_h = 34
    columns = 2 if relic_grid else 1 if has_icons else 2 if compact else 1
    per_col = (len(rows) + columns - 1) // columns
    gutter = 28 if relic_grid else 18
    col_w = (canvas_w - PAD * 2 - (gutter if columns == 2 else 0)) // columns
    h = header_h + per_col * row_h + foot_h + 10
    img = Image.new("RGB", (canvas_w, h), BG)
    draw = ImageDraw.Draw(img)

    draw.rectangle([(0, 0), (canvas_w, header_h)], fill=BG_HDR)
    draw.rectangle([(0, 0), (7, header_h)], fill=ACCENT)
    title_x = PAD
    if title_icon:
        icon = _open_icon(title_icon, 44)
        img.paste(icon, (PAD, 12), icon)
        title_x += 56
    draw.text((title_x, 12), f"{title} · {character_label}", fill=TEXT, font=f_t)
    draw.text((PAD, 54), f"{subtitle} · {ascension_label}", fill=SUB, font=f_s)
    if has_card_types:
        legend_x = PAD
        legend_y = 82
        for type_key, label in (("attack", "攻击"), ("skill", "技能"), ("power", "能力")):
            _draw_rank_bar(draw, legend_x, legend_y, 34, legend_y + 10, type_key)
            draw.text((legend_x + 42, legend_y - 4), label, fill=DIM, font=f_s)
            legend_x += 106

    def draw_column_header(x0: int, x1: int) -> None:
        label_y = header_h - 25
        draw.text((x0, label_y), "排名", fill=DIM, font=f_s)
        icon_size = 24 if compact else 30
        icon_x = x0 + (78 if compact else 88)
        name_x = icon_x + icon_size + 8 if has_icons else x0 + (110 if compact else 126)
        draw.text((name_x, label_y), "名称", fill=DIM, font=f_s)
        if compact:
            stat_x = x1 - (208 if has_icons else 170)
            sample_x = stat_x + (64 if has_icons else 70)
            pick_x = x1 - (74 if has_icons else 56)
            group_x = stat_x - (160 if has_icons else 82)
            draw.text((group_x, label_y), "类别", fill=DIM, font=f_s)
            draw.text((stat_x, label_y), "胜率", fill=DIM, font=f_s)
            draw.text((sample_x, label_y), "样本", fill=DIM, font=f_s)
            draw.text((pick_x, label_y), "选取", fill=DIM, font=f_s)
        else:
            stat_x = 390 if has_icons else 360
            draw.text((stat_x - 92, label_y), "类别", fill=DIM, font=f_s)
            draw.text((stat_x, label_y), "胜率", fill=DIM, font=f_s)
            draw.text((stat_x + 130, label_y), "样本", fill=DIM, font=f_s)
            draw.text((stat_x + 260, label_y), "选取", fill=DIM, font=f_s)

    for col in range(columns):
        hx0 = PAD + col * (col_w + gutter)
        draw_column_header(hx0, hx0 + col_w)
    draw.line([(PAD, header_h - 6), (canvas_w - PAD, header_h - 6)], fill=SEP)

    max_wr = max((float(r.get("win_rate") or 0) for r in rows), default=1.0) or 1.0
    min_wr = min((float(r.get("win_rate") or 0) for r in rows), default=0.0)
    span = max(1.0, max_wr - min_wr)
    for idx, row in enumerate(rows, 1):
        col = (idx - 1) // per_col
        pos = (idx - 1) % per_col
        x0 = PAD + col * (col_w + gutter)
        x1 = x0 + col_w
        y = header_h + pos * row_h
        draw.rectangle([(x0 - 8, y), (x1 + 8, y + row_h)], fill=BG if pos % 2 == 0 else ROW)
        wr = float(row.get("win_rate") or 0)
        ratio = (wr - min_wr) / span
        max_bar_w = 82 if compact else 190
        rank_min_w = 52 if relic_grid else 38
        bar_w = max(rank_min_w, int(max_bar_w * ratio))
        base_bar_h = 13 if compact else 18
        bar_h = max(base_bar_h + 1, round(base_bar_h * 1.5))
        bar_y0 = y + (row_h - bar_h) // 2
        bar_y1 = bar_y0 + bar_h
        _draw_rank_bar(draw, x0, bar_y0, bar_w, bar_y1, row.get("card_type"))
        rank_text = f"{idx:02d}" if idx < 100 else str(idx)
        draw.text((x0, y + (8 if compact else 10)), rank_text, fill=TEXT, font=f_s)

        icon_size = 24 if compact else 30
        icon_x = x0 + (78 if compact else 88)
        icon_y = y + (3 if compact else 6)
        if row.get("icon"):
            icon = _open_icon(row.get("icon"), icon_size)
            img.paste(icon, (icon_x, icon_y), icon)

        name_x = x0 + (110 if compact else 126)
        if has_icons:
            name_x = icon_x + icon_size + 8
        group = str(row.get("group") or "")
        if compact:
            stat_x = x1 - (208 if has_icons else 170)
            sample_x = stat_x + (64 if has_icons else 70)
            pick_x = x1 - (74 if has_icons else 56)
            group_w = 150 if has_icons and group else 70 if "·" in group else 42 if group else 0
            group_x = stat_x - (160 if has_icons else group_w + 10)
            name_max_w = max(72, group_x - name_x - 12)
            if has_icons:
                name_max_w = max(86, int(name_max_w * 1.2))
                name_max_w = min(name_max_w, max(86, group_x - name_x - 12))
            name_fill = _row_name_color(row)
            draw.text((name_x, y + 8), _truncate_text(draw, str(row.get("name") or row.get("id")), f_b, name_max_w), fill=name_fill, font=f_b)
            if group:
                draw.text((group_x, y + 10), _truncate_text(draw, group, f_s, group_w), fill=SUB, font=f_s)
            draw.text((stat_x, y + 8), f"{wr:.1f}%", fill=ACCENT, font=f_m)
            draw.text((sample_x, y + 9), _fmt_compact_int(row.get("picks")), fill=SUB, font=f_s)
            draw.text((pick_x, y + 8), _fmt_pct(row.get("pick_rate")), fill=SUB, font=f_s)
        else:
            stat_x = 390 if has_icons else 360
            group_w = 92 if "·" in group else 64 if group else 0
            name_max_w = max(130, stat_x - name_x - group_w - 14)
            name_fill = _row_name_color(row)
            draw.text((name_x, y + 8), _truncate_text(draw, str(row.get("name") or row.get("id")), f_b, name_max_w), fill=name_fill, font=f_b)
            if group:
                draw.text((name_x + name_max_w + 6, y + 12), _truncate_text(draw, group, f_s, group_w), fill=SUB, font=f_s)
            draw.text((stat_x, y + 10), f"胜率 {wr:.1f}%", fill=ACCENT, font=f_m)
            draw.text((stat_x + 130, y + 11), f"样本 {_fmt_int(row.get('picks'))}", fill=SUB, font=f_s)
            draw.text((stat_x + 260, y + 11), _fmt_pick_rate(row.get("pick_rate")), fill=SUB, font=f_s)
        draw.line([(x0, y + row_h - 1), (x1, y + row_h - 1)], fill=SEP)

    if columns == 2:
        mid = PAD + col_w + gutter // 2
        draw.line([(mid, header_h + 8), (mid, h - foot_h - 8)], fill=SEP)

    draw.rectangle([(0, h - foot_h), (canvas_w, h)], fill=BG_HDR)
    draw.text((PAD, h - 25), _truncate_text(draw, footnote, f_s, canvas_w - PAD * 2), fill=DIM, font=f_s)
    draw.rectangle([(0, 0), (canvas_w - 1, h - 1)], outline=SEP, width=2)
    return _buf(img)


def render_sts2_power_table_bundle(images: list[bytes], *, direction: str = "vertical") -> bytes:
    opened: list[Image.Image] = []
    for data in images:
        try:
            opened.append(Image.open(io.BytesIO(data)).convert("RGB"))
        except Exception:
            continue
    if not opened:
        return _buf(Image.new("RGB", (W, 120), BG))
    gap = 10
    if direction == "horizontal":
        width = sum(img.width for img in opened) + gap * (len(opened) - 1)
        height = max(img.height for img in opened)
    else:
        width = max(img.width for img in opened)
        height = sum(img.height for img in opened) + gap * (len(opened) - 1)
    out = Image.new("RGB", (width, height), BG)
    x = 0
    y = 0
    for img in opened:
        if direction == "horizontal":
            out.paste(img, (x, (height - img.height) // 2))
            x += img.width + gap
        else:
            out.paste(img, ((width - img.width) // 2, y))
            y += img.height + gap
    return _buf(out)
