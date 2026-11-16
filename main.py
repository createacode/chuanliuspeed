"""川流测速 - 本地网络测速工具.

原理：顺序下载若干真实文件源，记录实际下载字节数与耗时，计算下载速度，
并去掉一个最高值和一个最低值后取平均。所有数据、日志与临时文件均保存在
当前用户的数据目录中，不写入程序安装目录。

运行：
    python main.py [--host 127.0.0.1] [--port 8400] [--no-browser]
"""

from __future__ import annotations

import argparse
import atexit
import concurrent.futures
import copy
import ipaddress
import json
import logging
import os
import random
import re
import shutil
import socket
import string
import sys
import threading
import time
import uuid
import webbrowser
from dataclasses import dataclass, field
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from urllib.parse import urlsplit

import requests
from flask import Flask, jsonify, render_template, request
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from werkzeug.exceptions import HTTPException

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

APP_NAME = "川流测速"
APP_VERSION = "1.8.0"
CONFIG_SCHEMA_VERSION = 2

# 旧版本可能出现过的内置源 ID；用于判断是否需要补齐新内置源
LEGACY_BUILTIN_IDS = {
    "wps", "360", "wechat", "qq", "baidu", "dingtalk", "netease",
    "sogou", "xunlei", "cloudflare", "ovh",
}

DOWNLOAD_TIMEOUT_SECONDS = 60          # 单个源的下载总超时（秒）
MEASURE_DURATION_SECONDS = 8           # 每个源最多采样 8 秒，避免下载数 GB
SOCKET_READ_TIMEOUT_SECONDS = 15       # socket 读超时，保证“停止”能及时生效
CONNECT_TIMEOUT_SECONDS = 10
MAX_DOWNLOAD_BYTES = 256 * 1024 * 1024  # 单源最多写入 256 MB，防止磁盘被写满
MIN_VALID_DOWNLOAD_BYTES = 128 * 1024  # 小于 128 KB 视为无效样本
CHUNK_SIZE = 64 * 1024
MIN_SOURCES_FOR_TRIM = 4               # 至少 4 个有效源才去掉最高/最低值
MAX_SOURCES = 200
RESULT_RETENTION_DAYS = 90
LOG_RETENTION_DAYS = 90
MAX_NAME_LENGTH = 100
MAX_URL_LENGTH = 2048
SOURCE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

DEFAULT_SOURCES: dict[str, dict] = {
    "wps": {
        "name": "WPS Office",
        "url": "https://official-package.wpscdn.cn/wps/download/WPS_Setup_29690.exe",
        "size": "待验证",
        "enabled": True,
        "valid": False,
        "last_validation": "",
        "last_status": "待验证",
    },
    "360": {
        "name": "360安全卫士",
        "url": "https://sfdl.360safe.com/pclianmeng/n/1__4002009.exe",
        "size": "待验证",
        "enabled": True,
        "valid": False,
        "last_validation": "",
        "last_status": "待验证",
    },
    "wechat": {
        "name": "微信",
        "url": "https://dldir1v6.qq.com/weixin/Windows/WeChatSetup.exe",
        "size": "待验证",
        "enabled": True,
        "valid": False,
        "last_validation": "",
        "last_status": "待验证",
    },
    "baidupinyin": {
        "name": "百度输入法",
        "url": "https://imeres.baidu.com/imeres/imeres/ime-res/guanwang/dl/online/BaiduPinyinSetup_6.1.13.13.exe",
        "size": "待验证",
        "enabled": True,
        "valid": False,
        "last_validation": "",
        "last_status": "待验证",
    },
    "meeting": {
        "name": "腾讯会议",
        "url": "https://updatecdn.meeting.qq.com/cos/03001aa87c1fdfe02774f25175603db9/TencentMeeting_0300000000_3.48.0.443_x86_64.publish.exe",
        "size": "待验证",
        "enabled": True,
        "valid": False,
        "last_validation": "",
        "last_status": "待验证",
    },
    "tencentvideo": {
        "name": "腾讯视频",
        "url": "https://dldir1v6.qq.com/qqtv/TencentVideo11.189.7537.0.exe?support_redirect=1",
        "size": "待验证",
        "enabled": True,
        "valid": False,
        "last_validation": "",
        "last_status": "待验证",
    },
    "qqbrowser": {
        "name": "QQ浏览器",
        "url": "https://dldir1.qq.com/invc/tt/QQBrowser_Setup_11.1.5155.400.exe",
        "size": "待验证",
        "enabled": True,
        "valid": False,
        "last_validation": "",
        "last_status": "待验证",
    },
    "netease": {
        "name": "网易云音乐",
        "url": "https://d8.music.126.net/dmusic2/NeteaseCloudMusic_Music_official_3.1.43.205627_64.exe",
        "size": "待验证",
        "enabled": True,
        "valid": False,
        "last_validation": "",
        "last_status": "待验证",
    },
    "thunder": {
        "name": "迅雷",
        "url": "https://down.sandai.net/thunder_pc/ThunderSetup25.1.40.1705xl.exe",
        "size": "待验证",
        "enabled": True,
        "valid": False,
        "last_validation": "",
        "last_status": "待验证",
    },
    "iqiyi": {
        "name": "爱奇艺",
        "url": "https://mesh.if.iqiyi.com/player/upgrade/file/14.9.5.10287/IQIYIsetup_winget.exe",
        "size": "待验证",
        "enabled": True,
        "valid": False,
        "last_validation": "",
        "last_status": "待验证",
    },
    "youku": {
        "name": "优酷",
        "url": "https://pcclient.download.youku.com/iku-win-release/youkuclient_setup_9.2.66.1001.exe",
        "size": "待验证",
        "enabled": True,
        "valid": False,
        "last_validation": "",
        "last_status": "待验证",
    },
    "sogou": {
        "name": "搜狗输入法",
        "url": "https://ime.gtimg.com/pc/build/_sogou_pinyin_16.10.0.5858_0.exe",
        "size": "待验证",
        "enabled": True,
        "valid": False,
        "last_validation": "",
        "last_status": "待验证",
    },
    "bilibili": {
        "name": "哔哩哔哩",
        "url": "https://dl.hdslb.com/mobile/pack/bili_win/30389763/public/bilibili-setup-v1.20.0.exe",
        "size": "待验证",
        "enabled": True,
        "valid": False,
        "last_validation": "",
        "last_status": "待验证",
    },
}


# ---------------------------------------------------------------------------
# 运行时状态
# ---------------------------------------------------------------------------


@dataclass
class RuntimeState:
    """所有跨线程共享的可变状态都由 lock 保护。"""

    lock: threading.RLock = field(default_factory=threading.RLock)
    sources: dict[str, dict] = field(default_factory=dict)
    results: dict[str, dict] = field(default_factory=dict)
    active_selected: list[str] = field(default_factory=list)
    test_id: str | None = None
    is_testing: bool = False
    stop_event: threading.Event = field(default_factory=threading.Event)
    test_thread: threading.Thread | None = None
    active_downloads: dict[str, requests.Response] = field(default_factory=dict)
    validation_in_progress: bool = False
    validation_thread: threading.Thread | None = None


@dataclass
class DownloadOutcome:
    status: str
    downloaded: int = 0
    duration: float = 0.0
    speed_mbps: float = 0.0
    speed_mbs: float = 0.0
    total_size: int = 0
    sampled: bool = False


STATE = RuntimeState()
_CONFIG_WRITE_LOCK = threading.Lock()


# ---------------------------------------------------------------------------
# 路径与日志
# ---------------------------------------------------------------------------


def _is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def _base_dir() -> Path:
    if _is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


BASE_DIR = _base_dir()
DATA_DIR = Path()
CONFIG_FILE = Path()
CONFIG_STATE_FILE = Path()
TEMP_DIR = Path()
RESULT_DIR = Path()
LOG_DIR = Path()

SERVER_HOST = "127.0.0.1"
SERVER_PORT = 8400

logger = logging.getLogger("chuanliu")
action_logger = logging.getLogger("chuanliu.action")


def default_data_dir() -> Path:
    """按平台返回可写的用户数据目录。"""
    override = os.environ.get("CHUANLIU_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    if sys.platform == "win32":
        root = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(root) / "ChuanliuSpeed"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "ChuanliuSpeed"
    root = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(root) / "ChuanliuSpeed"


def configure_storage(data_dir: str | os.PathLike | None = None) -> None:
    """初始化数据目录（不创建全局副作用之外的任何状态）。"""
    global DATA_DIR, CONFIG_FILE, CONFIG_STATE_FILE, TEMP_DIR, RESULT_DIR, LOG_DIR
    DATA_DIR = Path(data_dir).expanduser().resolve() if data_dir else default_data_dir()
    CONFIG_FILE = DATA_DIR / "download_url.json"
    CONFIG_STATE_FILE = DATA_DIR / "config_state.json"
    TEMP_DIR = DATA_DIR / "临时下载"
    RESULT_DIR = DATA_DIR / "结果"
    LOG_DIR = DATA_DIR / "日志"
    for directory in (DATA_DIR, TEMP_DIR, RESULT_DIR, LOG_DIR):
        directory.mkdir(parents=True, exist_ok=True)


def setup_logging() -> None:
    """配置文件日志。窗口模式下 sys.stderr 为 None，不能盲目加 StreamHandler。"""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger.setLevel(logging.INFO)
    action_logger.setLevel(logging.INFO)

    if not any(isinstance(h, RotatingFileHandler) for h in logger.handlers):
        formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
        file_handler = RotatingFileHandler(
            LOG_DIR / "测速工具.log",
            maxBytes=10 * 1024 * 1024,
            backupCount=10,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        if sys.stderr is not None:  # 窗口模式下为 None
            stream_handler = logging.StreamHandler(sys.stderr)
            stream_handler.setFormatter(formatter)
            logger.addHandler(stream_handler)
    logger.propagate = False

    if not action_logger.handlers:
        action_handler = RotatingFileHandler(
            LOG_DIR / "用户操作.log",
            maxBytes=5 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        action_handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        action_logger.addHandler(action_handler)
    action_logger.propagate = False


def log_action(action: str) -> None:
    try:
        action_logger.info(action)
    except Exception:  # pragma: no cover - 日志失败不能影响主流程
        logger.exception("记录操作日志失败")


def purge_old_files(directory: Path, days: int, patterns: tuple[str, ...]) -> None:
    """清理超过保留期的结果/日志，避免无限增长。"""
    cutoff = time.time() - days * 86400
    try:
        for path in directory.iterdir():
            if not path.is_file():
                continue
            if not any(path.match(pattern) for pattern in patterns):
                continue
            try:
                if path.stat().st_mtime < cutoff:
                    path.unlink()
            except OSError:
                logger.warning("清理旧文件失败: %s", path)
    except OSError as exc:
        logger.warning("清理目录失败 %s: %s", directory, exc)


# ---------------------------------------------------------------------------
# 配置管理
# ---------------------------------------------------------------------------


def _safe_str(value: object, limit: int) -> str:
    if value is None:
        return ""
    text = str(value).replace("\x00", "").strip()
    return text[:limit]


def is_http_url(url: str) -> bool:
    """只允许 http/https，且拒绝带用户名密码的 URL。"""
    if not url or len(url) > MAX_URL_LENGTH:
        return False
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return False
    return not (parts.username or parts.password)


def is_public_url(url: str) -> bool:
    """在 is_http_url 基础上拒绝本机/内网/链路本地地址，避免被当作 SSRF 跳板。"""
    if not is_http_url(url):
        return False
    allow_private = os.environ.get("CHUANLIU_ALLOW_PRIVATE_URLS", "").lower() in {"1", "true", "yes"}
    if allow_private:
        return True
    host = (urlsplit(url).hostname or "").strip("[]").lower()
    if host in {"localhost", "localhost.localdomain"}:
        return False
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return True  # 域名交给系统解析，这里只拦截显式 IP
    return not (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    )


def normalize_source_id(raw_id: object, existing: set[str]) -> str:
    """把外部传入的 id 规范为安全字符，保证可以安全地写入 HTML 属性。"""
    candidate = _safe_str(raw_id, 64)
    if SOURCE_ID_RE.match(candidate):
        return candidate
    base = re.sub(r"[^A-Za-z0-9_-]+", "_", candidate).strip("_-")[:40] or "source"
    candidate = base
    index = 2
    while candidate in existing:
        candidate = f"{base[:56]}_{index}"
        index += 1
    return candidate


def sanitize_source(raw: object) -> dict | None:
    """校验并规范化单个下载源。非法数据返回 None。"""
    if not isinstance(raw, dict):
        return None
    name = _safe_str(raw.get("name"), MAX_NAME_LENGTH)
    url = _safe_str(raw.get("url"), MAX_URL_LENGTH)
    if not name or not is_http_url(url):
        return None
    return {
        "name": name,
        "url": url,
        "size": _safe_str(raw.get("size") or "待验证", 64),
        "enabled": bool(raw.get("enabled", True)),
        "valid": bool(raw.get("valid", False)),
        "last_validation": _safe_str(raw.get("last_validation"), 32),
        "last_status": _safe_str(raw.get("last_status"), 200),
    }


def save_config() -> bool:
    """原子写入配置文件。先写临时文件再 os.replace，避免并发写坏 JSON。"""
    with STATE.lock:
        snapshot = copy.deepcopy(STATE.sources)
    try:
        payload = json.dumps(snapshot, ensure_ascii=False, indent=2)
    except (TypeError, ValueError) as exc:
        logger.error("序列化配置失败: %s", exc)
        return False

    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp_file = CONFIG_FILE.with_name(CONFIG_FILE.name + ".tmp")
    try:
        with _CONFIG_WRITE_LOCK:
            with open(temp_file, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_file, CONFIG_FILE)
        return True
    except OSError as exc:
        logger.error("保存配置文件失败: %s", exc)
        try:
            temp_file.unlink(missing_ok=True)
        except OSError:
            pass
        return False


def _legacy_config_candidates() -> list[Path]:
    candidates = [BASE_DIR / "source" / "download_url.json", BASE_DIR / "download_url.json"]
    if _is_frozen():
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates.append(Path(meipass) / "source" / "download_url.json")
    return candidates


def migrate_legacy_config() -> None:
    """从旧版本位置迁移配置（只迁移，不覆盖已有新配置）。"""
    if CONFIG_FILE.exists():
        return
    for candidate in _legacy_config_candidates():
        try:
            if candidate.is_file():
                shutil.copy2(candidate, CONFIG_FILE)
                logger.info("已迁移旧配置文件: %s", candidate)
                return
        except OSError as exc:
            logger.warning("迁移旧配置失败 %s: %s", candidate, exc)


def _config_version() -> int:
    try:
        with open(CONFIG_STATE_FILE, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return int(data.get("version", 0))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return 0


def _save_config_version() -> None:
    try:
        CONFIG_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        temp_file = CONFIG_STATE_FILE.with_name(CONFIG_STATE_FILE.name + ".tmp")
        with open(temp_file, "w", encoding="utf-8", newline="\n") as handle:
            json.dump({"version": CONFIG_SCHEMA_VERSION}, handle)
        os.replace(temp_file, CONFIG_STATE_FILE)
    except OSError as exc:
        logger.warning("保存配置版本失败: %s", exc)


def load_config() -> None:
    """加载配置；损坏时备份并回退到默认值。"""
    sources: dict[str, dict] = {}
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            logger.error("配置文件损坏，将备份并使用默认配置: %s", exc)
            try:
                backup = CONFIG_FILE.with_name(
                    f"{CONFIG_FILE.name}.corrupt-{datetime.now().strftime('%Y%m%d%H%M%S')}"
                )
                os.replace(CONFIG_FILE, backup)
                logger.info("损坏的配置已备份到 %s", backup)
            except OSError:
                pass
            data = None

        if isinstance(data, dict):
            for raw_id, raw_source in data.items():
                source_id = normalize_source_id(raw_id, set(sources))
                source = sanitize_source(raw_source)
                if source is not None:
                    sources[source_id] = source
                else:
                    logger.warning("忽略无效配置项: %r", raw_id)

    version = _config_version()
    if not sources:
        sources = copy.deepcopy(DEFAULT_SOURCES)
        logger.info("使用内置默认下载源")
    elif version < CONFIG_SCHEMA_VERSION and (set(sources) & LEGACY_BUILTIN_IDS):
        # 升级时只补齐缺失的内置源，不删除、不覆盖用户自定义源
        added = 0
        for source_id, default in DEFAULT_SOURCES.items():
            if source_id not in sources:
                sources[source_id] = copy.deepcopy(default)
                added += 1
        if added:
            logger.info("配置升级：补充 %d 个内置下载源", added)

    with STATE.lock:
        STATE.sources = sources
    logger.info("成功加载配置，共 %d 个下载源", len(sources))
    save_config()
    _save_config_version()


def snapshot_sources() -> dict[str, dict]:
    with STATE.lock:
        return copy.deepcopy(STATE.sources)


# ---------------------------------------------------------------------------
# 网络测量
# ---------------------------------------------------------------------------


def new_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=2,
        connect=2,
        read=0,
        status=2,
        backoff_factor=0.4,
        status_forcelist=(500, 502, 503, 504),
        allowed_methods=frozenset(["HEAD", "GET"]),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=4, pool_maxsize=8)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.headers.update({"User-Agent": USER_AGENT})
    return session


def format_file_size(size_bytes: float) -> str:
    size_bytes = max(size_bytes, 0)
    if size_bytes < 1024:
        return f"{int(size_bytes)} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.2f} KB"
    if size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.2f} MB"
    return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


def _parse_content_range(value: str | None) -> int:
    if not value or "/" not in value:
        return 0
    total = value.rsplit("/", 1)[-1].strip()
    try:
        return max(int(total), 0)
    except ValueError:
        return 0


def get_file_size_from_url(url: str, timeout: int = CONNECT_TIMEOUT_SECONDS) -> str:
    """只读少量字节探测大小，绝不整包下载。"""
    if not is_http_url(url):
        return "未知大小"
    headers = {"Accept": "*/*"}
    try:
        with new_session() as session:
            try:
                response = session.head(url, headers=headers, timeout=timeout, allow_redirects=True)
                try:
                    if response.status_code in (200, 206):
                        length = response.headers.get("Content-Length")
                        if length and length.isdigit() and int(length) > 0:
                            return format_file_size(int(length))
                        ranged = _parse_content_range(response.headers.get("Content-Range"))
                        if ranged:
                            return format_file_size(ranged)
                finally:
                    response.close()
            except requests.RequestException:
                pass

            try:
                response = session.get(
                    url,
                    headers={**headers, "Range": "bytes=0-0"},
                    timeout=timeout,
                    stream=True,
                    allow_redirects=True,
                )
                try:
                    if response.status_code in (200, 206):
                        ranged = _parse_content_range(response.headers.get("Content-Range"))
                        if ranged:
                            return format_file_size(ranged)
                finally:
                    response.close()
            except requests.RequestException:
                pass
    except Exception as exc:  # pragma: no cover - 网络异常
        logger.warning("获取文件大小失败 %s: %s", url, exc)
    return "未知大小"


def _response_looks_measurable(response: requests.Response) -> bool:
    """验证阶段就排除 HTML 错误页和明显过小的响应。"""
    content_type = (response.headers.get("Content-Type") or "").lower()
    if content_type.startswith("text/") or "html" in content_type:
        return False
    if response.status_code == 206:
        total = _parse_content_range(response.headers.get("Content-Range"))
        if total and total < MIN_VALID_DOWNLOAD_BYTES:
            return False
        return True
    length = response.headers.get("Content-Length")
    if length is not None and length.strip().isdigit():
        return int(length) >= MIN_VALID_DOWNLOAD_BYTES
    return True


def validate_url(url: str, timeout: int = CONNECT_TIMEOUT_SECONDS) -> bool:
    """判断 URL 是否可访问且适合作为测速样本。HEAD 失败时用 Range GET 兜底。"""
    if not is_http_url(url):
        return False
    headers = {"Accept": "*/*"}
    try:
        with new_session() as session:
            try:
                response = session.head(url, headers=headers, timeout=timeout, allow_redirects=True)
                try:
                    if response.status_code in (200, 206) and _response_looks_measurable(response):
                        return True
                finally:
                    response.close()
            except requests.RequestException:
                pass
            try:
                response = session.get(
                    url,
                    headers={**headers, "Range": "bytes=0-0"},
                    timeout=timeout,
                    stream=True,
                    allow_redirects=True,
                )
                try:
                    return (
                        response.status_code in (200, 206)
                        and _response_looks_measurable(response)
                    )
                finally:
                    response.close()
            except requests.RequestException:
                return False
    except Exception as exc:  # pragma: no cover
        logger.warning("验证 URL 失败 %s: %s", url, exc)
        return False


def _short_error(exc: BaseException) -> str:
    text = str(exc).replace("\r", " ").replace("\n", " ").strip()
    return text[:200] or exc.__class__.__name__


def download_file(
    test_id: str,
    source_id: str,
    url: str,
    file_path: Path,
    stop_event: threading.Event,
    progress_callback=None,
    speed_callback=None,
) -> DownloadOutcome:
    """下载单个文件并返回测量结果。这是测速的唯一数据来源。"""
    started = time.monotonic()
    downloaded = 0
    total_size = 0
    status = "成功"
    sampled = False
    response: requests.Response | None = None
    session: requests.Session | None = None
    key = f"{test_id}:{source_id}"

    try:
        session = new_session()
        response = session.get(
            url,
            headers={
                "Accept": "*/*",
                # 不请求压缩，否则 Content-Length 与实际写入字节数不一致
                "Accept-Encoding": "identity",
                "Connection": "keep-alive",
            },
            timeout=(CONNECT_TIMEOUT_SECONDS, SOCKET_READ_TIMEOUT_SECONDS),
            stream=True,
            allow_redirects=True,
        )
        with STATE.lock:
            STATE.active_downloads[key] = response

        if response.status_code not in (200, 206):
            status = f"HTTP {response.status_code}"
            return DownloadOutcome(status=status)

        content_type = (response.headers.get("Content-Type") or "").lower()
        # 公网 URL 不允许被重定向到内网/回环地址（SSRF）；显式允许内网时不拦截。
        if is_public_url(url) and not is_public_url(response.url):
            status = "重定向到非公网地址"
            return DownloadOutcome(status=status)
        if content_type.startswith("text/") or "html" in content_type:
            status = "无效响应(HTML)"
            return DownloadOutcome(status=status)

        length_header = response.headers.get("Content-Length")
        if length_header and length_header.isdigit():
            total_size = int(length_header)

        last_progress = started
        last_speed = started
        last_size = 0
        with open(file_path, "wb") as handle:
            for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
                if stop_event.is_set():
                    status = "用户停止"
                    break
                now = time.monotonic()
                if now - started > DOWNLOAD_TIMEOUT_SECONDS:
                    status = f"超时({DOWNLOAD_TIMEOUT_SECONDS}秒)"
                    break
                if not chunk:
                    continue
                if downloaded + len(chunk) > MAX_DOWNLOAD_BYTES:
                    # 达到写入上限时，已采集的数据仍然可以用于测速
                    sampled = downloaded >= MIN_VALID_DOWNLOAD_BYTES
                    if not sampled:
                        status = "超过下载上限"
                    break
                handle.write(chunk)
                downloaded += len(chunk)

                if progress_callback and now - last_progress >= 0.25:
                    progress_callback(downloaded, total_size, now - started)
                    last_progress = now
                if speed_callback and now - last_speed >= 1.0:
                    elapsed_delta = now - last_speed
                    speed_bps = (downloaded - last_size) / elapsed_delta if elapsed_delta > 0 else 0
                    speed_callback(
                        speed_bps * 8 / 1_000_000,
                        speed_bps / (1024 * 1024),
                        now - started,
                    )
                    last_speed = now
                    last_size = downloaded

                # 稳定采样：默认只测 8 秒，避免大安装包把流量和磁盘写满
                if (
                    now - started >= MEASURE_DURATION_SECONDS
                    and downloaded >= MIN_VALID_DOWNLOAD_BYTES
                ):
                    sampled = True
                    break

        duration = max(time.monotonic() - started, 1e-6)
        if status == "成功":
            if downloaded < MIN_VALID_DOWNLOAD_BYTES:
                status = "数据不足"
            elif not sampled and total_size > 0 and downloaded < total_size:
                status = "下载不完整"
    except requests.exceptions.Timeout:
        status = f"超时({DOWNLOAD_TIMEOUT_SECONDS}秒)"
    except Exception as exc:
        if stop_event.is_set():
            status = "用户停止"
        elif "IncompleteRead" in repr(exc) or "Content-Length" in repr(exc):
            status = "下载不完整"
        else:
            status = f"错误: {_short_error(exc)}"
        logger.warning("下载失败 %s: %s", url, exc)
    finally:
        with STATE.lock:
            STATE.active_downloads.pop(key, None)
        if response is not None:
            try:
                response.close()
            except Exception:
                pass
        if session is not None:
            session.close()

    duration = max(time.monotonic() - started, 1e-6)
    if status == "成功" and duration > 0:
        speed_bps = downloaded / duration
        return DownloadOutcome(
            status=status,
            downloaded=downloaded,
            duration=duration,
            speed_mbps=speed_bps * 8 / 1_000_000,
            speed_mbs=speed_bps / (1024 * 1024),
            total_size=total_size,
            sampled=sampled,
        )
    return DownloadOutcome(
        status=status,
        downloaded=downloaded,
        duration=duration,
        total_size=total_size,
        sampled=sampled,
    )


# ---------------------------------------------------------------------------
# 平均值计算
# ---------------------------------------------------------------------------


def compute_average(results: dict[str, dict]) -> tuple[float, float, list[str]]:
    """计算平均速度并返回可直接展示的步骤。有效源 >= 4 时去掉最高/最低。"""
    valid: list[tuple[float, float]] = []
    for result in results.values():
        if (
            result.get("status") == "成功"
            and result.get("time") is not None
            and float(result.get("speed_mbps") or 0) > 0
        ):
            valid.append((float(result["speed_mbps"]), float(result.get("speed_mbs") or 0)))

    steps = [f"计算时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"]
    if not valid:
        steps.append("无有效测试结果")
        return 0.0, 0.0, steps

    steps.append(f"有效测试源数量: {len(valid)}")
    raw = sorted(valid, key=lambda item: item[0])
    steps.append(f"原始速度数据(Mbps): {[round(item[0], 2) for item in raw]}")

    selected = raw
    if len(raw) >= MIN_SOURCES_FOR_TRIM:
        steps.append(f"去掉最高值: {raw[-1][0]:.2f} Mbps")
        steps.append(f"去掉最低值: {raw[0][0]:.2f} Mbps")
        selected = raw[1:-1]
        steps.append(f"处理后速度数据(Mbps): {[round(item[0], 2) for item in selected]}")
    else:
        steps.append(f"有效源不足 {MIN_SOURCES_FOR_TRIM} 个，不去除极值")

    avg_mbps = sum(item[0] for item in selected) / len(selected)
    avg_mbs = sum(item[1] for item in selected) / len(selected)
    steps.append(f"平均下载速度: {avg_mbps:.2f} Mbps / {avg_mbs:.2f} MB/s")
    return avg_mbps, avg_mbs, steps


def save_test_result(test_id: str, results: dict[str, dict]) -> tuple[Path | None, float, float]:
    """保存文本结果，返回 (路径, 平均 Mbps, 平均 MB/s)。"""
    avg_mbps, avg_mbs, steps = compute_average(results)
    try:
        result_file = RESULT_DIR / f"{test_id}_测试结果.txt"
        with open(result_file, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(f"测速测试结果 - {test_id}\n")
            handle.write("=" * 50 + "\n\n")
            handle.write("测试配置:\n")
            handle.write(f"测试时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            handle.write(f"测试源数量: {len(results)}\n\n")
            handle.write("详细结果:\n")
            handle.write("-" * 80 + "\n")
            for result in results.values():
                handle.write(f"名称: {result.get('name', '')}\n")
                handle.write(f"URL: {result.get('url', '')}\n")
                handle.write(f"状态: {result.get('status', '')}\n")
                if result.get("status") == "成功":
                    handle.write(f"下载时间: {float(result.get('time') or 0):.2f} 秒\n")
                    handle.write(
                        f"下载速度: {float(result.get('speed_mbps') or 0):.2f} Mbps"
                        f" / {float(result.get('speed_mbs') or 0):.2f} MB/s\n"
                    )
                    if result.get("sampled"):
                        handle.write(f"测量方式: 前 {MEASURE_DURATION_SECONDS} 秒采样\n")
                handle.write(f"已下载大小: {format_file_size(float(result.get('downloaded_size') or 0))}\n")
                handle.write("-" * 80 + "\n")
            handle.write("\n平均速度计算过程:\n")
            handle.write("-" * 80 + "\n")
            for step in steps:
                handle.write(f"{step}\n")
            if avg_mbps > 0:
                handle.write(f"\n最终平均下载速度: {avg_mbps:.2f} Mbps / {avg_mbs:.2f} MB/s\n")
            else:
                handle.write("\n无有效测试结果\n")
        logger.info("测试结果已保存: %s", result_file)
        return result_file, avg_mbps, avg_mbs
    except OSError as exc:
        logger.error("保存测试结果失败: %s", exc)
        return None, 0.0, 0.0


# ---------------------------------------------------------------------------
# 测试流程
# ---------------------------------------------------------------------------


def _set_result(test_id: str, source_id: str, result: dict) -> None:
    with STATE.lock:
        if STATE.test_id != test_id:
            return
        STATE.results[source_id] = result


def _patch_result(test_id: str, source_id: str, **fields) -> None:
    with STATE.lock:
        if STATE.test_id != test_id:
            return
        result = STATE.results.get(source_id)
        if result is not None:
            result.update(fields)


def _update_source_status(test_id: str, source_id: str, status: str) -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with STATE.lock:
        if STATE.test_id != test_id:
            return
        source = STATE.sources.get(source_id)
        if source is not None:
            source["last_status"] = status[:200]
            source["last_validation"] = now


def clean_temp_dir() -> None:
    try:
        for path in TEMP_DIR.iterdir():
            try:
                if path.is_file() or path.is_symlink():
                    path.unlink()
                elif path.is_dir():
                    shutil.rmtree(path)
            except OSError as exc:
                logger.warning("删除临时文件失败 %s: %s", path, exc)
    except OSError as exc:
        logger.warning("清理临时目录失败: %s", exc)


def run_download_test(test_id: str, selected_ids: list[str], stop_event: threading.Event) -> None:
    try:
        prune_temp_files()
        for index, source_id in enumerate(selected_ids):
            if stop_event.is_set():
                break
            with STATE.lock:
                if STATE.test_id != test_id:
                    return
                source = copy.deepcopy(STATE.sources.get(source_id))
            if not source:
                continue

            name = source.get("name", source_id)
            url = source.get("url", "")
            _set_result(
                test_id,
                source_id,
                {
                    "name": name,
                    "url": url,
                    "downloaded_size": 0,
                    "total_size": 0,
                    "status": "测试中...",
                    "time": None,
                    "speed_mbps": 0,
                    "speed_mbs": 0,
                    "progress": 0,
                    "elapsed_time": 0,
                    "current_speed_mbps": 0,
                    "current_speed_mbs": 0,
                    "sampled": False,
                },
            )

            temp_file = TEMP_DIR / f"{test_id}_{index}.part"

            def on_progress(downloaded: int, total: int, elapsed: float, sid: str = source_id) -> None:
                progress = (downloaded / total * 100) if total > 0 else 0
                _patch_result(
                    test_id,
                    sid,
                    downloaded_size=downloaded,
                    total_size=total,
                    progress=progress,
                    elapsed_time=elapsed,
                )

            def on_speed(mbps: float, mbs: float, elapsed: float, sid: str = source_id) -> None:
                _patch_result(
                    test_id,
                    sid,
                    current_speed_mbps=mbps,
                    current_speed_mbs=mbs,
                    elapsed_time=elapsed,
                )

            logger.info("开始测试: %s (%s)", name, url)
            outcome = download_file(
                test_id,
                source_id,
                url,
                temp_file,
                stop_event,
                progress_callback=on_progress,
                speed_callback=on_speed,
            )

            _update_source_status(test_id, source_id, outcome.status)
            _set_result(
                test_id,
                source_id,
                {
                    "name": name,
                    "url": url,
                    "downloaded_size": outcome.downloaded,
                    "total_size": outcome.total_size,
                    "status": outcome.status,
                    "time": outcome.duration if outcome.status == "成功" else None,
                    "speed_mbps": outcome.speed_mbps,
                    "speed_mbs": outcome.speed_mbs,
                    "progress": 100 if outcome.status == "成功" else 0,
                    "elapsed_time": outcome.duration,
                    "current_speed_mbps": 0,
                    "current_speed_mbs": 0,
                    "sampled": outcome.sampled,
                },
            )
            try:
                temp_file.unlink(missing_ok=True)
            except OSError:
                pass
            logger.info("测试完成: %s - %s", name, outcome.status)

        with STATE.lock:
            if STATE.test_id != test_id:
                return
            results_snapshot = copy.deepcopy(STATE.results)

        if results_snapshot:
            _, avg_mbps, avg_mbs = save_test_result(test_id, results_snapshot)
            logger.info("平均下载速度: %.2f Mbps / %.2f MB/s", avg_mbps, avg_mbs)
        save_config()
    except Exception:
        logger.exception("下载测试执行失败")
    finally:
        with STATE.lock:
            current = STATE.test_id == test_id
            if current:
                STATE.is_testing = False
                STATE.active_downloads.clear()
        if current:
            clean_temp_dir()


def prune_temp_files() -> None:
    """测试开始前清理上一次遗留的临时文件。"""
    try:
        for path in TEMP_DIR.glob("*.part"):
            try:
                path.unlink()
            except OSError:
                pass
    except OSError:
        pass


def stop_all_downloads() -> None:
    """请求停止并关闭所有活跃连接，使阻塞在 read 的线程尽快退出。"""
    with STATE.lock:
        STATE.stop_event.set()
        responses = list(STATE.active_downloads.values())
    for response in responses:
        try:
            response.close()
        except Exception:
            pass
    logger.info("已请求停止所有下载")


def start_download_test(selected_ids: list[str]) -> tuple[bool, str, str | None]:
    with STATE.lock:
        if STATE.is_testing:
            return False, "测试正在进行中", None
        if STATE.validation_in_progress:
            return False, "正在验证下载源，请稍候再开始测试", None
        ids: list[str] = []
        for raw_id in selected_ids:
            if (
                isinstance(raw_id, str)
                and raw_id in STATE.sources
                and STATE.sources[raw_id].get("enabled", True)
                and raw_id not in ids
            ):
                ids.append(raw_id)
        if not ids:
            return False, "请选择至少一个下载源", None
        if len(ids) > MAX_SOURCES:
            return False, f"单次测试最多支持 {MAX_SOURCES} 个下载源", None

        test_id = (
            f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_"
            f"{''.join(random.choices(string.digits, k=4))}"
        )
        STATE.results = {}
        STATE.active_selected = ids
        STATE.test_id = test_id
        STATE.is_testing = True
        STATE.stop_event = threading.Event()
        thread = threading.Thread(
            target=run_download_test,
            args=(test_id, ids, STATE.stop_event),
            name="speed-test",
            daemon=True,
        )
        STATE.test_thread = thread
    thread.start()
    log_action(f"开始测试 {test_id}，共 {len(ids)} 个源")
    return True, "测试已开始", test_id


def reset_runtime_state() -> dict[str, dict]:
    """停止测试、清空结果并返回当前下载源快照。"""
    with STATE.lock:
        STATE.stop_event.set()
        thread = STATE.test_thread
    stop_all_downloads()
    if thread is not None and thread.is_alive():
        thread.join(timeout=10)
    with STATE.lock:
        STATE.test_id = None
        STATE.is_testing = False
        STATE.results = {}
        STATE.active_selected = []
        STATE.test_thread = None
        STATE.stop_event = threading.Event()
    clean_temp_dir()
    log_action("重置所有状态")
    return snapshot_sources()


# ---------------------------------------------------------------------------
# 下载源验证
# ---------------------------------------------------------------------------


def _validate_source(source_id: str, url: str) -> tuple[str, bool, str, str]:
    valid = validate_url(url)
    if valid:
        size = get_file_size_from_url(url)
        return source_id, True, size, "验证成功"
    return source_id, False, "链接不可用", "验证失败"


def _validation_worker(source_ids: list[str]) -> None:
    try:
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with STATE.lock:
            urls = {
                source_id: STATE.sources[source_id]["url"]
                for source_id in source_ids
                if source_id in STATE.sources
            }
        if not urls:
            return
        with concurrent.futures.ThreadPoolExecutor(max_workers=5, thread_name_prefix="validator") as pool:
            futures = {pool.submit(_validate_source, sid, url): sid for sid, url in urls.items()}
            for future in concurrent.futures.as_completed(futures):
                source_id = futures[future]
                try:
                    sid, valid, size, status = future.result()
                except Exception as exc:  # pragma: no cover - 防御
                    logger.warning("验证源 %s 失败: %s", source_id, exc)
                    sid, valid, size, status = source_id, False, "验证失败", "验证异常"
                with STATE.lock:
                    source = STATE.sources.get(sid)
                    if source is not None:
                        source["valid"] = valid
                        source["size"] = size
                        source["last_validation"] = current_time
                        source["last_status"] = status
        save_config()
        logger.info("验证完成，共验证 %d 个源", len(urls))
    except Exception:
        logger.exception("验证线程执行失败")
    finally:
        with STATE.lock:
            STATE.validation_in_progress = False
            STATE.validation_thread = None


def start_validation(source_ids: list[str] | None = None) -> tuple[bool, str]:
    with STATE.lock:
        if STATE.is_testing:
            return False, "测速进行中，为避免干扰测量，请先停止测试"
        if STATE.validation_in_progress:
            return False, "验证正在进行中，请稍候"
        ids = [
            sid
            for sid in (source_ids if source_ids is not None else list(STATE.sources))
            if isinstance(sid, str) and sid in STATE.sources
        ]
        if not ids:
            return False, "没有可验证的下载源"
        STATE.validation_in_progress = True
        thread = threading.Thread(target=_validation_worker, args=(ids,), name="validator", daemon=True)
        STATE.validation_thread = thread
    thread.start()
    log_action(f"开始验证 {len(ids)} 个下载源")
    return True, "验证已开始，请等待完成"


def _validation_after_current(source_ids: list[str]) -> None:
    """等待当前测试/验证结束后再开始验证。"""
    while True:
        with STATE.lock:
            busy = STATE.validation_in_progress or STATE.is_testing
        if not busy:
            ok, _ = start_validation(source_ids)
            if ok:
                return
        time.sleep(0.5)


# ---------------------------------------------------------------------------
# Flask 应用
# ---------------------------------------------------------------------------

app = Flask(__name__, static_folder="static", template_folder="templates")
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0
try:  # Flask >= 2.2
    app.json.ensure_ascii = False
    app.json.sort_keys = False
except AttributeError:  # pragma: no cover
    pass


@app.after_request
def add_security_headers(response):
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
        "connect-src 'self'; font-src 'self'; object-src 'none'; base-uri 'self'; "
        "form-action 'self'; frame-ancestors 'none'",
    )
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
    return response


@app.before_request
def protect_api():
    """所有写操作要求自定义请求头，阻止跨站表单 CSRF。"""
    if request.path.startswith("/api/") and request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        if request.headers.get("X-Requested-With") != "XMLHttpRequest":
            return jsonify({"success": False, "message": "非法请求来源"}), 403
        origin = request.headers.get("Origin")
        if origin:
            try:
                origin_host = urlsplit(origin).netloc
            except ValueError:
                origin_host = ""
            if origin_host.lower() != request.host.lower():
                return jsonify({"success": False, "message": "非法请求来源"}), 403
    return None


def _json_body() -> dict | None:
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else None


@app.route("/")
def index():
    return render_template(
        "index.html",
        version=APP_VERSION,
        port=SERVER_PORT,
        timeout=DOWNLOAD_TIMEOUT_SECONDS,
    )


@app.get("/api/config")
def get_config():
    with STATE.lock:
        validation_in_progress = STATE.validation_in_progress
    return jsonify(
        success=True,
        sources=snapshot_sources(),
        validation_in_progress=validation_in_progress,
        version=APP_VERSION,
    )


@app.post("/api/validate")
def validate_sources():
    data = _json_body()
    requested = data.get("sources") if data else None
    if requested is not None and not isinstance(requested, list):
        return jsonify({"success": False, "message": "sources 必须是数组"}), 400
    if requested is not None:
        requested = [sid for sid in requested if isinstance(sid, str)]
    ok, message = start_validation(requested)
    if not ok:
        return jsonify({"success": False, "message": message}), 409
    return jsonify({"success": True, "message": message})


@app.post("/api/test")
def start_test():
    data = _json_body()
    if data is None:
        return jsonify({"success": False, "message": "请求体必须是 JSON 对象"}), 400
    selected = data.get("sources")
    if not isinstance(selected, list) or not selected:
        return jsonify({"success": False, "message": "请选择至少一个下载源"}), 400
    ok, message, test_id = start_download_test(selected)
    if not ok:
        status = 409 if ("正在进行" in message or "正在验证" in message) else 400
        return jsonify({"success": False, "message": message}), status
    return jsonify({"success": True, "test_id": test_id, "message": message})


@app.post("/api/stop")
def stop_testing():
    with STATE.lock:
        is_testing = STATE.is_testing
    if not is_testing:
        return jsonify({"success": False, "message": "没有正在进行的测试"}), 400
    stop_all_downloads()
    log_action("停止测试")
    return jsonify({"success": True, "message": "停止请求已发送"})


@app.post("/api/reset")
def reset_test():
    sources = reset_runtime_state()
    return jsonify({"success": True, "message": "所有状态已重置", "sources": sources})


def _status_payload() -> dict:
    with STATE.lock:
        results = copy.deepcopy(STATE.results)
        is_testing = STATE.is_testing
        test_id = STATE.test_id
        total_count = len(STATE.active_selected)

    testing_count = 0
    completed_count = 0
    success_count = 0
    failed_count = 0
    for result in results.values():
        if result.get("status") in ("测试中...", "测试中"):
            testing_count += 1
        else:
            completed_count += 1
            if result.get("status") == "成功":
                success_count += 1
            else:
                failed_count += 1

    avg_mbps, avg_mbs, steps = compute_average(results)
    calculation_process = "\n".join(steps) if results else ""
    return {
        "success": True,
        "is_testing": is_testing,
        "test_id": test_id,
        "total_count": total_count,
        "results": results,
        "avg_speed_mbps": avg_mbps,
        "avg_speed_mbs": avg_mbs,
        "calculation_process": calculation_process,
        "stats": {
            "testing_count": testing_count,
            "completed_count": completed_count,
            "success_count": success_count,
            "failed_count": failed_count,
        },
    }


@app.get("/api/status")
def get_test_status():
    return jsonify(_status_payload())


@app.post("/api/config/update")
def update_config():
    data = _json_body()
    if data is None:
        return jsonify({"success": False, "message": "请求体必须是 JSON 对象"}), 400
    action = data.get("action")
    message = ""
    result_id = None

    with STATE.lock:
        if action == "add":
            name = _safe_str(data.get("name"), MAX_NAME_LENGTH)
            url = _safe_str(data.get("url"), MAX_URL_LENGTH)
            if not name or not url:
                return jsonify({"success": False, "message": "名称和 URL 不能为空"}), 400
            if not is_public_url(url):
                return (
                    jsonify(
                        {
                            "success": False,
                            "message": "URL 必须是公网 http/https 地址"
                            "（如需测试内网地址，请设置 CHUANLIU_ALLOW_PRIVATE_URLS=1）",
                        }
                    ),
                    400,
                )
            if len(STATE.sources) >= MAX_SOURCES:
                return jsonify({"success": False, "message": f"下载源数量不能超过 {MAX_SOURCES}"}), 400
            source_id = f"custom_{uuid.uuid4().hex[:10]}"
            result_id = source_id
            STATE.sources[source_id] = {
                "name": name,
                "url": url,
                "size": "待验证",
                "enabled": True,
                "valid": False,
                "last_validation": "",
                "last_status": "待验证",
            }
            message = "下载源已添加"

        elif action == "update":
            source_id = data.get("id")
            if not isinstance(source_id, str) or source_id not in STATE.sources:
                return jsonify({"success": False, "message": "下载源不存在"}), 404
            result_id = source_id
            name = _safe_str(data.get("name"), MAX_NAME_LENGTH)
            url = _safe_str(data.get("url"), MAX_URL_LENGTH)
            source = STATE.sources[source_id]
            if name:
                source["name"] = name
            if url and url != source["url"]:
                if not is_public_url(url):
                    return (
                        jsonify(
                            {
                                "success": False,
                                "message": "URL 必须是公网 http/https 地址"
                                "（如需测试内网地址，请设置 CHUANLIU_ALLOW_PRIVATE_URLS=1）",
                            }
                        ),
                        400,
                    )
                source["url"] = url
                source["valid"] = False
                source["size"] = "待验证"
                source["last_status"] = "待验证"
                source["last_validation"] = ""
                message = "下载源已更新，请重新验证"
            else:
                message = "下载源已更新"

        elif action == "delete":
            source_id = data.get("id")
            if not isinstance(source_id, str) or source_id not in STATE.sources:
                return jsonify({"success": False, "message": "下载源不存在"}), 404
            STATE.sources.pop(source_id)
            STATE.active_selected = [sid for sid in STATE.active_selected if sid != source_id]
            message = "下载源已删除"

        elif action == "toggle":
            source_id = data.get("id")
            if not isinstance(source_id, str) or source_id not in STATE.sources:
                return jsonify({"success": False, "message": "下载源不存在"}), 404
            STATE.sources[source_id]["enabled"] = bool(data.get("enabled", True))
            message = "下载源状态已更新"

        elif action == "toggle_all":
            enabled = bool(data.get("enabled", True))
            for source in STATE.sources.values():
                source["enabled"] = enabled
            message = "已更新全部下载源状态"

        else:
            return jsonify({"success": False, "message": "未知操作"}), 400

        save_config()

    log_action(message)
    return jsonify(
        {"success": True, "message": message, "id": result_id, "sources": snapshot_sources()}
    )


@app.post("/api/config/import")
def import_config():
    data = _json_body()
    if data is None:
        return jsonify({"success": False, "message": "无效的 JSON 数据"}), 400

    new_sources: dict[str, dict] = {}
    for raw_id, raw_source in data.items():
        if len(new_sources) >= MAX_SOURCES:
            break
        source_id = normalize_source_id(raw_id, set(new_sources))
        source = sanitize_source(raw_source)
        if source is None or not is_public_url(source["url"]):
            continue
        source["valid"] = False
        source["last_validation"] = ""
        source["last_status"] = "待验证"
        new_sources[source_id] = source

    if not new_sources:
        return jsonify({"success": False, "message": "没有有效的下载源数据（仅支持公网 http/https URL）"}), 400

    with STATE.lock:
        STATE.sources = new_sources
        STATE.active_selected = [sid for sid in STATE.active_selected if sid in STATE.sources]
        save_config()
    log_action(f"批量导入下载源，共 {len(new_sources)} 个")

    if start_validation(list(new_sources)):
        message = f"成功导入 {len(new_sources)} 个下载源，正在验证..."
    else:
        threading.Thread(
            target=_validation_after_current,
            args=(list(new_sources),),
            name="validator-queue",
            daemon=True,
        ).start()
        message = f"成功导入 {len(new_sources)} 个下载源，验证将自动开始"
    return jsonify({"success": True, "message": message, "sources": snapshot_sources()})


@app.errorhandler(HTTPException)
def handle_http_exception(error: HTTPException):
    if request.path.startswith("/api/"):
        return jsonify({"success": False, "message": error.description}), error.code or 500
    return error


@app.errorhandler(404)
def not_found(_error):
    if request.path.startswith("/api/"):
        return jsonify({"success": False, "message": "接口不存在"}), 404
    return "页面不存在", 404


@app.errorhandler(405)
def method_not_allowed(_error):
    if request.path.startswith("/api/"):
        return jsonify({"success": False, "message": "请求方法不允许"}), 405
    return "请求方法不允许", 405


@app.errorhandler(413)
def payload_too_large(_error):
    if request.path.startswith("/api/"):
        return jsonify({"success": False, "message": "请求体过大"}), 413
    return "请求体过大", 413


@app.errorhandler(Exception)
def unexpected_error(error):
    logger.exception("未处理的异常: %s", error)
    if request.path.startswith("/api/"):
        return jsonify({"success": False, "message": "服务器内部错误"}), 500
    return "服务器内部错误", 500


# ---------------------------------------------------------------------------
# 启动
# ---------------------------------------------------------------------------


class SingleInstanceLock:
    """防止重复启动多个实例同时写配置。"""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.handle = None

    def acquire(self) -> bool:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.handle = open(self.path, "a+", encoding="utf-8")  # noqa: SIM115
            # 先确保文件至少有一个字节，再锁定第 0 字节。
            self.handle.seek(0)
            self.handle.truncate()
            self.handle.write("0")
            self.handle.flush()
            self.handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.handle.seek(0)
            self.handle.truncate()
            self.handle.write(str(os.getpid()))
            self.handle.flush()
            return True
        except OSError:
            if self.handle is not None:
                try:
                    self.handle.close()
                except OSError:
                    pass
            return False

    def release(self) -> None:
        if self.handle is None:
            return
        try:
            if os.name == "nt":
                import msvcrt

                self.handle.seek(0)
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        try:
            self.handle.close()
        except OSError:
            pass
        self.handle = None


def _port_in_use(host: str, port: int) -> bool:
    probe_host = "127.0.0.1" if host in {"0.0.0.0", "::", ""} else host
    try:
        with socket.create_connection((probe_host, port), timeout=0.4):
            return True
    except OSError:
        return False


def _browser_url(host: str, port: int) -> str:
    if host in {"0.0.0.0", "::", ""}:
        host = "127.0.0.1"
    return f"http://{host}:{port}"


def _open_browser_when_ready(url: str, host: str, port: int) -> None:
    probe_host = "127.0.0.1" if host in {"0.0.0.0", "::", ""} else host
    for _ in range(150):
        try:
            with socket.create_connection((probe_host, port), timeout=0.3):
                break
        except OSError:
            time.sleep(0.1)
    try:
        webbrowser.open(url)
    except Exception:
        logger.warning("自动打开浏览器失败，请手动访问 %s", url)


def _show_fatal_error(message: str) -> None:
    try:
        logger.error(message)
    except Exception:
        pass
    if sys.stderr is not None:
        try:
            sys.stderr.write(message + "\n")
        except Exception:
            pass
    if os.name == "nt":
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(None, message, APP_NAME, 0x10)
        except Exception:
            pass


def serve(host: str, port: int) -> None:
    try:
        from waitress import serve as waitress_serve

        logger.info("使用 waitress 启动服务: http://%s:%d", host, port)
        waitress_serve(app, host=host, port=port, threads=8)
    except ImportError:  # pragma: no cover - 依赖缺失时的兜底
        logger.warning("未安装 waitress，回退到 Flask 内置服务器")
        app.run(host=host, port=port, debug=False, use_reloader=False, threaded=True)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=f"{APP_NAME} v{APP_VERSION}")
    parser.add_argument("--host", default=os.environ.get("CHUANLIU_HOST", "127.0.0.1"))
    try:
        default_port = int(os.environ.get("CHUANLIU_PORT", "8400"))
    except ValueError:
        default_port = 8400
    parser.add_argument("--port", type=int, default=default_port)
    parser.add_argument("--data-dir", default=os.environ.get("CHUANLIU_DATA_DIR"))
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {APP_VERSION}")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    global SERVER_HOST, SERVER_PORT
    # PyInstaller 窗口模式下 sys.stdout / sys.stderr 为 None；
    # 指向 devnull 以避免 argparse（--help/--version）等库调用崩溃。
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")
    args = parse_args(argv)
    if not args.host or not str(args.host).strip():
        _show_fatal_error("监听地址不能为空")
        return 2
    if not (1 <= args.port <= 65535):
        _show_fatal_error("端口必须在 1-65535 之间")
        return 2
    SERVER_HOST = args.host
    SERVER_PORT = args.port

    try:
        configure_storage(args.data_dir)
        setup_logging()
    except OSError as exc:
        _show_fatal_error(f"无法初始化数据目录 {DATA_DIR}: {exc}")
        return 1

    logger.info("%s v%s 启动，数据目录: %s", APP_NAME, APP_VERSION, DATA_DIR)
    purge_old_files(RESULT_DIR, RESULT_RETENTION_DAYS, ("*_测试结果.txt",))
    purge_old_files(LOG_DIR, LOG_RETENTION_DAYS, ("用户操作.log*", "测速工具.log*"))

    lock = SingleInstanceLock(DATA_DIR / "app.lock")
    if not lock.acquire():
        url = _browser_url(SERVER_HOST, SERVER_PORT)
        logger.warning("检测到已有实例在运行，直接打开浏览器: %s", url)
        if not args.no_browser:
            _open_browser_when_ready(url, SERVER_HOST, SERVER_PORT)
        return 0
    atexit.register(lock.release)

    if _port_in_use(SERVER_HOST, SERVER_PORT):
        _show_fatal_error(f"端口 {SERVER_PORT} 已被占用，请使用 --port 指定其他端口。")
        return 1

    migrate_legacy_config()
    load_config()
    atexit.register(stop_all_downloads)

    if not args.no_browser:
        threading.Thread(
            target=_open_browser_when_ready,
            args=(_browser_url(SERVER_HOST, SERVER_PORT), SERVER_HOST, SERVER_PORT),
            name="browser-opener",
            daemon=True,
        ).start()

    start_validation()
    try:
        serve(SERVER_HOST, SERVER_PORT)
    except OSError as exc:
        _show_fatal_error(f"启动服务失败: {exc}")
        return 1
    except KeyboardInterrupt:
        logger.info("收到退出信号")
    finally:
        stop_all_downloads()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
