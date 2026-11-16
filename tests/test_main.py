"""川流测速后端单元测试 / 接口测试。

运行：
    .venv/Scripts/python.exe -m pytest -q
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

import main


@pytest.fixture()
def app_client(tmp_path, monkeypatch):
    """每个测试使用独立数据目录和干净的全局状态。"""
    main.configure_storage(tmp_path)
    with main.STATE.lock:
        main.STATE.sources = {}
        main.STATE.results = {}
        main.STATE.active_selected = []
        main.STATE.test_id = None
        main.STATE.is_testing = False
        main.STATE.stop_event = threading.Event()
        main.STATE.test_thread = None
        main.STATE.active_downloads.clear()
        main.STATE.validation_in_progress = False
        main.STATE.validation_thread = None
    main.load_config()
    main.app.config.update(TESTING=True)
    with main.app.test_client() as client:
        yield client


def post(client, path, payload=None, with_header=True):
    headers = {"X-Requested-With": "XMLHttpRequest"} if with_header else {}
    return client.post(path, json=payload if payload is not None else {}, headers=headers)


# ---------------------------------------------------------------------------
# 纯函数
# ---------------------------------------------------------------------------


def test_format_file_size():
    assert main.format_file_size(0) == "0 B"
    assert main.format_file_size(512) == "512 B"
    assert main.format_file_size(1536) == "1.50 KB"
    assert main.format_file_size(1024 * 1024) == "1.00 MB"
    assert main.format_file_size(1024 ** 3) == "1.00 GB"
    assert main.format_file_size(-10) == "0 B"


def make_result(speed_mbps, status="成功"):
    return {
        "status": status,
        "time": 1.0 if status == "成功" else None,
        "speed_mbps": speed_mbps,
        "speed_mbs": speed_mbps / 8.388608,
    }


def test_compute_average_no_results():
    avg, avg_mbs, steps = main.compute_average({})
    assert avg == 0
    assert avg_mbs == 0
    assert "无有效测试结果" in steps


def test_compute_average_does_not_trim_three_sources():
    results = {str(i): make_result(float(i)) for i in (10, 20, 30)}
    avg, _, steps = main.compute_average(results)
    assert avg == pytest.approx(20.0)
    assert any("不去除极值" in step for step in steps)


def test_compute_average_trims_with_four_sources():
    results = {str(i): make_result(float(i)) for i in (10, 20, 30, 40)}
    avg, avg_mbs, steps = main.compute_average(results)
    assert avg == pytest.approx(25.0)
    assert avg_mbs == pytest.approx(25.0 / 8.388608)
    assert any("去掉最高值" in step for step in steps)


def test_compute_average_ignores_failed_sources():
    results = {
        "ok1": make_result(10),
        "ok2": make_result(20),
        "bad": {"status": "超时(60秒)", "time": None, "speed_mbps": 999, "speed_mbs": 999},
    }
    avg, _, steps = main.compute_average(results)
    assert avg == pytest.approx(15.0)
    assert any("有效测试源数量: 2" in step for step in steps)


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://example.com/file.exe", True),
        ("http://example.com/file.exe", True),
        ("ftp://example.com/file.exe", False),
        ("file:///C:/windows/notepad.exe", False),
        ("javascript:alert(1)", False),
        ("https://user:pass@example.com/x", False),
        ("", False),
    ],
)
def test_is_http_url(url, expected):
    assert main.is_http_url(url) is expected


def test_is_public_url_blocks_private_addresses(monkeypatch):
    monkeypatch.delenv("CHUANLIU_ALLOW_PRIVATE_URLS", raising=False)
    assert main.is_public_url("https://example.com/a.exe") is True
    for url in (
        "http://127.0.0.1:8400/api/config",
        "http://localhost/x",
        "http://10.0.0.5/x",
        "http://192.168.1.1/x",
        "http://169.254.169.254/latest/meta-data/",
        "http://[::1]/x",
    ):
        assert main.is_public_url(url) is False, url


def test_normalize_source_id():
    existing = set()
    assert main.normalize_source_id("abc-123", existing) == "abc-123"
    safe = main.normalize_source_id('<img src=x onerror=alert(1)>', existing)
    assert main.SOURCE_ID_RE.match(safe)
    assert "<" not in safe and '"' not in safe


def test_sanitize_source_rejects_invalid():
    assert main.sanitize_source("not-a-dict") is None
    assert main.sanitize_source({"name": "", "url": "https://example.com/a"}) is None
    assert main.sanitize_source({"name": "x", "url": "ftp://example.com/a"}) is None
    clean = main.sanitize_source({"name": "x", "url": "https://example.com/a.exe"})
    assert clean is not None
    assert clean["size"] == "待验证"


# ---------------------------------------------------------------------------
# 页面与接口
# ---------------------------------------------------------------------------


def test_index_renders_without_inline_scripts_or_styles(app_client):
    response = app_client.get("/")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "川流测速" in body
    assert "v1.8.0" in body
    assert "单个超时: 60秒" in body
    assert "本地端口: 8400" in body
    assert "/static/app.css" in body
    assert "/static/app.js" in body
    assert "<style" not in body
    assert "style=" not in body
    assert "onerror=" not in body
    csp = response.headers.get("Content-Security-Policy", "")
    assert "default-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp
    assert response.headers.get("X-Content-Type-Options") == "nosniff"


def test_static_assets_served(app_client):
    assert app_client.get("/static/app.js").status_code == 200
    assert app_client.get("/static/app.css").status_code == 200
    assert app_client.get("/static/chart.js").status_code == 200


def test_config_returns_defaults(app_client):
    response = app_client.get("/api/config")
    data = response.get_json()
    assert data["success"] is True
    assert data["version"] == main.APP_VERSION
    assert len(data["sources"]) == len(main.DEFAULT_SOURCES)
    assert data["validation_in_progress"] is False
    for source in data["sources"].values():
        assert main.is_http_url(source["url"])
        assert "size" in source


def test_post_requires_csrf_header(app_client):
    response = app_client.post("/api/stop")
    assert response.status_code == 403
    assert response.get_json()["success"] is False


def test_cross_origin_post_rejected(app_client):
    response = app_client.post(
        "/api/stop",
        headers={"X-Requested-With": "XMLHttpRequest", "Origin": "https://evil.example"},
    )
    assert response.status_code == 403


def test_stop_without_test_returns_400(app_client):
    response = post(app_client, "/api/stop")
    assert response.status_code == 400


def test_add_update_delete_source(app_client):
    response = post(
        app_client,
        "/api/config/update",
        {"action": "add", "name": "测试源", "url": "https://example.com/a.exe"},
    )
    data = response.get_json()
    assert data["success"] is True
    source_id = data["id"]
    assert main.SOURCE_ID_RE.match(source_id)
    assert data["sources"][source_id]["name"] == "测试源"

    with main.STATE.lock:
        main.STATE.sources[source_id]["valid"] = True
        main.STATE.sources[source_id]["size"] = "1.00 MB"

    # 只改名字、URL 不变，不应把源重置为待验证
    response = post(
        app_client,
        "/api/config/update",
        {"action": "update", "id": source_id, "name": "新名字", "url": "https://example.com/a.exe"},
    )
    data = response.get_json()
    assert data["sources"][source_id]["name"] == "新名字"
    assert data["sources"][source_id]["valid"] is True
    assert data["sources"][source_id]["size"] == "1.00 MB"

    # 改 URL 才需要重新验证
    response = post(
        app_client,
        "/api/config/update",
        {"action": "update", "id": source_id, "name": "新名字", "url": "https://example.com/b.exe"},
    )
    data = response.get_json()
    assert data["sources"][source_id]["valid"] is False
    assert data["sources"][source_id]["size"] == "待验证"

    response = post(app_client, "/api/config/update", {"action": "delete", "id": source_id})
    assert response.status_code == 200
    assert source_id not in response.get_json()["sources"]


def test_add_rejects_private_and_invalid_url(app_client):
    for url in ("http://127.0.0.1/x", "ftp://example.com/x", "not-a-url"):
        response = post(
            app_client,
            "/api/config/update",
            {"action": "add", "name": "x", "url": url},
        )
        assert response.status_code == 400, url


def test_update_unknown_source_404(app_client):
    response = post(app_client, "/api/config/update", {"action": "delete", "id": "nope"})
    assert response.status_code == 404


def test_toggle_all(app_client):
    response = post(app_client, "/api/config/update", {"action": "toggle_all", "enabled": False})
    data = response.get_json()
    assert all(source["enabled"] is False for source in data["sources"].values())


def test_import_sanitizes_ids(app_client, monkeypatch):
    monkeypatch.setattr(main, "start_validation", lambda ids=None: (True, "stub"))
    payload = {
        'bad id " onmouseover="alert(1)': {
            "name": "<script>alert(1)</script>",
            "url": "https://example.com/a.exe",
        },
        "ok": {"name": "正常", "url": "https://example.com/b.exe"},
    }
    response = post(app_client, "/api/config/import", payload)
    data = response.get_json()
    assert response.status_code == 200
    assert data["success"] is True
    assert "ok" in data["sources"]
    for source_id in data["sources"]:
        assert main.SOURCE_ID_RE.match(source_id)
    bad_ids = [sid for sid in data["sources"] if sid != "ok"]
    assert len(bad_ids) == 1
    assert all(source["valid"] is False for source in data["sources"].values())


def test_import_rejects_array_and_private_sources(app_client, monkeypatch):
    monkeypatch.setattr(main, "start_validation", lambda ids=None: (True, "stub"))
    response = post(app_client, "/api/config/import", [])
    assert response.status_code == 400
    response = post(
        app_client,
        "/api/config/import",
        {"x": {"name": "local", "url": "http://192.168.1.2/a.exe"}},
    )
    assert response.status_code == 400


def test_status_empty_shape(app_client):
    data = app_client.get("/api/status").get_json()
    assert data["success"] is True
    assert data["is_testing"] is False
    assert data["results"] == {}
    assert data["total_count"] == 0
    assert set(data["stats"]) == {"testing_count", "completed_count", "success_count", "failed_count"}


def test_start_test_rejects_missing_sources(app_client):
    assert post(app_client, "/api/test", {}).status_code == 400
    assert post(app_client, "/api/test", {"sources": []}).status_code == 400


def test_start_test_blocked_while_validating(app_client):
    source_id = next(iter(main.STATE.sources))
    with main.STATE.lock:
        main.STATE.validation_in_progress = True
    try:
        response = post(app_client, "/api/test", {"sources": [source_id]})
        assert response.status_code == 409
        assert "验证" in response.get_json()["message"]
    finally:
        with main.STATE.lock:
            main.STATE.validation_in_progress = False


def test_validation_blocked_while_testing(app_client):
    with main.STATE.lock:
        main.STATE.is_testing = True
    try:
        response = post(app_client, "/api/validate", {"sources": []})
        assert response.status_code == 409
        assert "测速" in response.get_json()["message"]
    finally:
        with main.STATE.lock:
            main.STATE.is_testing = False


def test_start_validation_sets_flag_and_rejects_duplicate(app_client, monkeypatch):
    release = threading.Event()

    def fake_worker(_ids):
        release.wait(5)

    monkeypatch.setattr(main, "_validation_worker", fake_worker)
    source_id = next(iter(main.STATE.sources))
    try:
        ok, _ = main.start_validation([source_id])
        assert ok is True
        assert main.STATE.validation_in_progress is True
        ok_again, message = main.start_validation([source_id])
        assert ok_again is False
        assert "正在进行" in message
    finally:
        release.set()
        thread = main.STATE.validation_thread
        if thread is not None:
            thread.join(timeout=5)
        with main.STATE.lock:
            main.STATE.validation_in_progress = False
            main.STATE.validation_thread = None


def test_disabled_sources_cannot_start_test(app_client):
    source_id = next(iter(main.STATE.sources))
    with main.STATE.lock:
        main.STATE.sources[source_id]["enabled"] = False
    response = post(app_client, "/api/test", {"sources": [source_id]})
    assert response.status_code == 400
    assert "请选择" in response.get_json()["message"]


def test_save_test_result(tmp_path, app_client):
    results = {
        "a": {
            "name": "A",
            "url": "https://example.com/a.exe",
            "status": "成功",
            "time": 1.0,
            "speed_mbps": 80.0,
            "speed_mbs": 9.5,
            "downloaded_size": 10 * 1024 * 1024,
        },
        "b": {
            "name": "B",
            "url": "https://example.com/b.exe",
            "status": "超时(60秒)",
            "time": None,
            "speed_mbps": 0,
            "speed_mbs": 0,
            "downloaded_size": 1024,
        },
    }
    path, avg, avg_mbs = main.save_test_result("20260101_000000_1234", results)
    assert path is not None and path.exists()
    text = path.read_text(encoding="utf-8")
    assert "测速测试结果" in text
    assert "A" in text
    assert "超时" in text
    assert avg == pytest.approx(80.0)
    assert avg_mbs == pytest.approx(9.5)


# ---------------------------------------------------------------------------
# 真实 HTTP 下载测量（本地服务器，不访问外网）
# ---------------------------------------------------------------------------


class _PayloadHandler(BaseHTTPRequestHandler):
    payload = b""
    content_length = None
    content_type = "application/octet-stream"

    def do_GET(self):  # noqa: N802
        if self.path == "/html":
            body = b"<html><body>error</body></html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        declared = self.content_length if self.content_length is not None else len(self.payload)
        self.send_response(200)
        self.send_header("Content-Type", self.content_type)
        self.send_header("Content-Length", str(declared))
        self.end_headers()
        self.wfile.write(self.payload)
        self.wfile.flush()

    def log_message(self, *_args):  # 静默
        pass


@pytest.fixture()
def http_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _PayloadHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()


def test_download_file_success(tmp_path, http_server):
    _PayloadHandler.payload = b"x" * (256 * 1024)
    _PayloadHandler.content_length = None
    url = f"http://127.0.0.1:{http_server.server_port}/file.bin"
    target = tmp_path / "out.bin"
    stop = threading.Event()
    outcome = main.download_file("tid", "sid", url, target, stop)
    assert outcome.status == "成功", outcome.status
    assert outcome.downloaded == 256 * 1024
    assert outcome.speed_mbps > 0
    assert target.exists()


def test_upgrade_merges_new_builtin_sources_once(tmp_path):
    main.configure_storage(tmp_path)
    with main.STATE.lock:
        main.STATE.sources = {}
    old_config = {
        "wps": {
            "name": "WPS Office",
            "url": "https://official-package.wpscdn.cn/wps/download/WPS_Setup_29690.exe",
            "size": "297.40 MB",
            "enabled": True,
            "valid": True,
            "last_validation": "2026-01-01 00:00:00",
            "last_status": "验证成功",
        },
        "my_custom": {
            "name": "自定义源",
            "url": "https://example.com/custom.exe",
            "size": "待验证",
            "enabled": True,
            "valid": False,
            "last_validation": "",
            "last_status": "待验证",
        },
    }
    main.CONFIG_FILE.write_text(json.dumps(old_config, ensure_ascii=False), encoding="utf-8")
    main.load_config()

    with main.STATE.lock:
        sources = dict(main.STATE.sources)
    # 已有的自定义源和旧内置源保留，新增内置源被补齐
    assert "my_custom" in sources
    assert sources["wps"]["valid"] is True
    assert "bilibili" in sources
    assert "baidupinyin" in sources
    assert len(sources) > len(old_config)
    assert main.CONFIG_STATE_FILE.exists()

    # 升级只执行一次：用户之后删除的源不会被再次自动加回
    with main.STATE.lock:
        main.STATE.sources.pop("bilibili")
    main.save_config()
    main.load_config()
    with main.STATE.lock:
        assert "bilibili" not in main.STATE.sources


def test_download_file_samples_large_files(tmp_path, http_server, monkeypatch):
    monkeypatch.setattr(main, "MEASURE_DURATION_SECONDS", 0)
    _PayloadHandler.payload = b"x" * (2 * 1024 * 1024)
    _PayloadHandler.content_length = None
    url = f"http://127.0.0.1:{http_server.server_port}/large"
    target = tmp_path / "out.bin"
    outcome = main.download_file("tid", "sid", url, target, threading.Event())
    assert outcome.status == "成功"
    assert outcome.sampled is True
    assert 0 < outcome.downloaded < 2 * 1024 * 1024
    assert outcome.speed_mbps > 0


def test_validate_url_rejects_html_and_small_files(http_server):
    base = f"http://127.0.0.1:{http_server.server_port}"

    _PayloadHandler.content_length = None
    _PayloadHandler.payload = b"x" * (256 * 1024)
    assert main.validate_url(base + "/big") is True

    _PayloadHandler.payload = b"x" * (10 * 1024)
    assert main.validate_url(base + "/small") is False

    assert main.validate_url(base + "/html") is False


def test_download_file_rejects_html(tmp_path, http_server):
    url = f"http://127.0.0.1:{http_server.server_port}/html"
    outcome = main.download_file("tid", "sid", url, tmp_path / "out.bin", threading.Event())
    assert outcome.status == "无效响应(HTML)"


def test_download_file_detects_incomplete(tmp_path, http_server):
    _PayloadHandler.payload = b"x" * (150 * 1024)
    _PayloadHandler.content_length = 500 * 1024
    url = f"http://127.0.0.1:{http_server.server_port}/partial"
    outcome = main.download_file("tid", "sid", url, tmp_path / "out.bin", threading.Event())
    assert outcome.status == "下载不完整", outcome.status


def test_download_file_stop(tmp_path, http_server):
    _PayloadHandler.payload = b"x" * (2 * 1024 * 1024)
    _PayloadHandler.content_length = None
    url = f"http://127.0.0.1:{http_server.server_port}/big"
    stop = threading.Event()
    result = {}

    def run():
        result["outcome"] = main.download_file("tid", "sid", url, tmp_path / "out.bin", stop)

    thread = threading.Thread(target=run)
    thread.start()
    # 等下载开始后再请求停止
    for _ in range(100):
        with main.STATE.lock:
            if main.STATE.active_downloads:
                break
        threading.Event().wait(0.01)
    stop.set()
    with main.STATE.lock:
        for response in list(main.STATE.active_downloads.values()):
            response.close()
    thread.join(timeout=15)
    assert not thread.is_alive()
    assert result["outcome"].status in {"用户停止", "成功", "数据不足"}


def test_config_file_is_atomic_and_reloadable(tmp_path, app_client):
    post(app_client, "/api/config/update", {"action": "toggle_all", "enabled": False})
    data = json.loads(main.CONFIG_FILE.read_text(encoding="utf-8"))
    assert data
    assert all(source["enabled"] is False for source in data.values())
    # 临时文件不应残留
    assert not main.CONFIG_FILE.with_name(main.CONFIG_FILE.name + ".tmp").exists()
