from __future__ import annotations

import asyncio
import hashlib
import io
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional

import aiohttp
from astrbot.api import logger
from PIL import Image, ImageDraw, ImageFont

from .paths import STS2_IMAGE_CACHE_DIR


# ──────────────────────────────────────────────────────────────────────────────
# 图片缩放因子（2 = 高清 2x 输出，适配移动端高分辨率屏幕）
# ──────────────────────────────────────────────────────────────────────────────

_SCALE = 2


# ──────────────────────────────────────────────────────────────────────────────
# CJK 字体查找（Pillow）
# ──────────────────────────────────────────────────────────────────────────────

_CJK_FONT_SEARCH_PATHS: list[Path] = [
    # Windows
    Path("C:/Windows/Fonts/msyh.ttc"),
    Path("C:/Windows/Fonts/msyhbd.ttc"),
    Path("C:/Windows/Fonts/simhei.ttf"),
    Path("C:/Windows/Fonts/simsun.ttc"),
    Path("C:/Windows/Fonts/simkai.ttf"),
    # Linux — WenQuanYi（Docker / Ubuntu 常见）
    Path("/usr/share/fonts/truetype/wqy/wqy-microhei.ttc"),
    Path("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"),
    # Linux — Noto CJK
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-VF.otf"),
    Path("/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc"),
    Path("/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf"),
    Path("/usr/share/fonts/truetype/noto/NotoSansCJKsc-Regular.otf"),
    Path("/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc"),
    Path("/usr/share/fonts/noto/NotoSansCJKsc-Regular.otf"),
    Path("/usr/share/fonts/noto/NotoSerifCJKsc-Regular.otf"),
    # Linux — 其他常见路径
    Path("/usr/share/fonts/truetype/arphic/uming.ttc"),
    Path("/usr/share/fonts/truetype/arphic/ukai.ttc"),
    Path("/usr/share/fonts/chinese/TrueType/uming.ttf"),
    # macOS
    Path("/System/Library/Fonts/PingFang.ttc"),
    Path("/System/Library/Fonts/STHeiti Light.ttc"),
    Path("/Library/Fonts/Arial Unicode.ttf"),
]

# 自动下载字体时保存到此路径
_DOWNLOADED_FONT_PATH: Optional[Path] = None

# 候选下载 URL（从可靠 CDN 获取，按优先级排列）
_FONT_DOWNLOAD_URLS: list[str] = [
    # jsDelivr 镜像 GitHub 的 wqy-microhei（中国可用）
    "https://cdn.jsdelivr.net/gh/Hacker0x01/hacker-fonts@master/fonts/WenQuanYi-Micro-Hei-Mono.ttf",
    # Noto Sans CJK SC（SourceForge 镜像）
    "https://downloads.sourceforge.net/project/cjkfonts/NotoSansCJK-OTF/1.004/NotoSansCJKsc-Regular.otf",
]


def _find_cjk_font_via_fc_list() -> Optional[Path]:
    """在 Linux/macOS 上通过 fc-list 动态查找中文字体。"""
    if not shutil.which("fc-list"):
        return None
    try:
        result = subprocess.run(
            ["fc-list", ":lang=zh", "--format=%{file}\n"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        for line in result.stdout.strip().splitlines():
            p = Path(line.strip())
            if p.exists() and p.suffix.lower() in (".ttc", ".ttf", ".otf"):
                return p
    except Exception as e:
        logger.debug(f"[sts2_stats] fc-list 查找字体失败: {e}")
    return None


def _find_cjk_font(extra_paths: list[Path] | None = None) -> Optional[Path]:
    search = (extra_paths or []) + _CJK_FONT_SEARCH_PATHS
    for p in search:
        if p.exists():
            return p
    found = _find_cjk_font_via_fc_list()
    if found:
        logger.info(f"[sts2_stats] 通过 fc-list 找到 CJK 字体: {found}")
    return found


_CJK_FONT_PATH: Optional[Path] = _find_cjk_font()

if not _CJK_FONT_PATH:
    logger.warning(
        "[sts2_stats] 未找到 CJK 字体文件，图片中中文可能显示为方框。\n"
        "        Linux 可执行：apt-get install -y fonts-noto-cjk  或  fonts-wqy-microhei\n"
        "        也可在插件设置 cjk_font_path 中手动指定字体文件路径，\n"
        "        或将字体文件放入 data/plugin_data/astrbot_plugin_sts2_stats/fonts/ 目录。"
    )


# ──────────────────────────────────────────────────────────────────────────────
# 运行时字体下载（初始化时调用，确保 Docker 环境也能显示中文）
# ──────────────────────────────────────────────────────────────────────────────

async def ensure_cjk_font(data_dir: Path) -> None:
    """若系统中找不到 CJK 字体，尝试从 CDN 自动下载到本地缓存。
    应在 initialize() 中以异步方式调用。
    """
    global _CJK_FONT_PATH, _DOWNLOADED_FONT_PATH

    if _CJK_FONT_PATH:
        return

    # 模块 import 时可能尚未安装系统字体，初始化时再扫一遍（含 fc-list）
    found = _find_cjk_font()
    if found:
        configure_cjk_font(str(found))
        return

    fonts_dir = data_dir / "fonts"
    # 先检查之前下载过的字体
    candidate = _find_cjk_font(list(fonts_dir.glob("*")) if fonts_dir.exists() else [])
    if candidate:
        configure_cjk_font(str(candidate))
        return

    fonts_dir.mkdir(parents=True, exist_ok=True)
    save_path = fonts_dir / "wqy-microhei.ttf"

    logger.info("[sts2_stats] 未找到 CJK 字体，尝试自动下载中文字体（首次启动需要一点时间）…")

    downloaded = False
    async with aiohttp.ClientSession() as session:
        for url in _FONT_DOWNLOAD_URLS:
            try:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=60)) as resp:
                    if resp.status == 200:
                        content = await resp.read()
                        # 粗略验证：字体文件应大于 1 MB
                        if len(content) > 1_000_000:
                            save_path.write_bytes(content)
                            downloaded = True
                            logger.info(f"[sts2_stats] CJK 字体下载成功，保存至: {save_path}")
                            break
                        else:
                            logger.debug(f"[sts2_stats] 字体文件过小，跳过 URL: {url}")
            except Exception as e:
                logger.debug(f"[sts2_stats] 字体下载失败 ({url}): {e}")

    if downloaded and save_path.exists():
        configure_cjk_font(str(save_path))
    else:
        logger.warning(
            "[sts2_stats] 自动下载 CJK 字体失败，中文将显示为方框。\n"
            f"        请手动将 .ttf/.ttc/.otf 字体文件放入 {fonts_dir}/ 目录，\n"
            "        或在插件设置中指定 cjk_font_path。"
        )


def configure_cjk_font(path: str) -> None:
    """从插件配置中设置 CJK 字体路径（覆盖自动探测结果）。"""
    global _CJK_FONT_PATH
    if not path:
        return
    p = Path(path)
    if not p.exists():
        logger.warning(f"[sts2_stats] 配置的 cjk_font_path 不存在: {path}")
        return
    if p == _CJK_FONT_PATH:
        return
    _font_cache.clear()
    _CJK_FONT_PATH = p
    logger.info(f"[sts2_stats] CJK 字体已从配置覆盖: {p}")

# ──────────────────────────────────────────────────────────────────────────────
# PIL 字体加载（带缓存）
# ──────────────────────────────────────────────────────────────────────────────

_font_cache: dict[int, ImageFont.FreeTypeFont | ImageFont.ImageFont] = {}


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    if size in _font_cache:
        return _font_cache[size]
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont
    if _CJK_FONT_PATH:
        try:
            font = ImageFont.truetype(str(_CJK_FONT_PATH), size)
            _font_cache[size] = font
            return font
        except OSError:
            pass
    for p in _CJK_FONT_SEARCH_PATHS:
        if p.exists():
            try:
                font = ImageFont.truetype(str(p), size)
                _font_cache[size] = font
                return font
            except OSError:
                continue
    font = ImageFont.load_default()
    _font_cache[size] = font
    return font


def _open_icon(icon_bytes: bytes | None, size: int = 144) -> Image.Image:
    if not icon_bytes:
        return Image.new("RGBA", (size, size), (60, 60, 70, 255))
    try:
        img = Image.open(io.BytesIO(icon_bytes)).convert("RGBA")
        img.thumbnail((size, size), Image.Resampling.LANCZOS)
        canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        ox = (size - img.width) // 2
        oy = (size - img.height) // 2
        canvas.paste(img, (ox, oy), img)
        return canvas
    except Exception as e:
        logger.debug(f"[sts2_stats] 图标解码失败: {e}")
        return Image.new("RGBA", (size, size), (80, 80, 90, 255))


def _wrap_text(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> list[str]:
    lines: list[str] = []
    for paragraph in text.split("\n"):
        if not paragraph:
            lines.append("")
            continue
        current = ""
        for ch in paragraph:
            test = current + ch
            if draw.textlength(test, font=font) <= max_width:
                current = test
            else:
                if current:
                    lines.append(current)
                current = ch
        if current:
            lines.append(current)
    return lines or [""]


def _truncate_text(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> str:
    # PIL textlength 不支持多行文本，先折叠换行符
    text = text.replace("\n", " ").replace("\r", "")
    if draw.textlength(text, font=font) <= max_width:
        return text
    ellipsis = "..."
    for i in range(len(text), 0, -1):
        candidate = text[:i] + ellipsis
        if draw.textlength(candidate, font=font) <= max_width:
            return candidate
    return ellipsis


def _icon_cache_path(
    oid: str, url: str, cache_dir: Path | None = None
) -> Path:
    """按 objectID + pic URL 生成缓存路径；URL 变更时自动使用新文件。"""
    safe_oid = re.sub(r"[^\w.\-]", "_", str(oid))[:80]
    url_hash = hashlib.sha256(url.encode()).hexdigest()[:16]
    base = cache_dir if cache_dir is not None else STS2_IMAGE_CACHE_DIR
    return base / f"{safe_oid}_{url_hash}.bin"


async def download_icon(
    session: aiohttp.ClientSession,
    url: str | None,
    *,
    oid: str | None = None,
    cache_dir: Path | None = None,
) -> bytes | None:
    """下载物品图标；若提供 oid 则读写本地磁盘缓存。

    默认缓存目录：data/plugin_data/astrbot_plugin_sts2_stats/sts2_icon_cache/
    可通过 cache_dir 指定其他目录（如 item_icon_cache）。
    """
    if not url:
        return None

    cache_path: Path | None = (
        _icon_cache_path(oid, url, cache_dir) if oid else None
    )
    if cache_path and cache_path.exists():
        try:
            data = await asyncio.to_thread(cache_path.read_bytes)
            if data:
                return data
        except Exception as e:
            logger.debug(f"[sts2_stats] 读取图标缓存失败 {cache_path}: {e}")

    try:
        async with session.get(
            url, timeout=aiohttp.ClientTimeout(total=15)
        ) as resp:
            if resp.status == 200:
                data = await resp.read()
                if data and cache_path:
                    cache_path.parent.mkdir(parents=True, exist_ok=True)
                    await asyncio.to_thread(cache_path.write_bytes, data)
                return data
    except Exception as e:
        logger.debug(f"[sts2_stats] 下载图标失败 {url}: {e}")
    return None


async def save_png(path: Path, png_bytes: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    await asyncio.to_thread(path.write_bytes, png_bytes)
    return path
