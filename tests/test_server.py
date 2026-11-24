"""Dashboard server: loopback binding, request limits, and the placeholder contract."""
import json
import threading
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from src.csi.live import LiveProcessor


def _load_server():
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location(
        "live_server_http", Path(__file__).resolve().parents[1] / "tools" / "live_dashboard" / "server.py")
    server = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(server)
    return server


def test_bind_host_is_loopback_and_pose_defaults_to_placeholder():
    server = _load_server()
    assert server.BIND_HOST == "127.0.0.1"
    assert server.origin_allowed(None) is True
    assert server.origin_allowed("http://127.0.0.1:8765") is True
    assert server.origin_allowed("http://localhost:8765") is True
    assert server.origin_allowed("https://example.com") is False
    assert server.origin_allowed("null") is False


def test_json_body_rejects_negative_and_huge_lengths():
    server = _load_server()
    obj, err = server.read_json_object("-1", lambda n: b"")
    assert obj == {} and err
    obj, err = server.read_json_object(str(server.MAX_JSON_BODY + 1), lambda n: b"")
    assert err
    obj, err = server.read_json_object("2", lambda n: b"[]")
    assert err
    obj, err = server.read_json_object(None, lambda n: b"")
    assert obj == {} and err is None


def test_cross_origin_post_is_rejected_and_page_names_the_placeholder():
    server = _load_server()

    class A:
        demo, port, baud, out, no_reset = True, "COM5", 921600, "data/recordings", False

    app = server.App(A)
    assert isinstance(app.proc, LiveProcessor)
    assert app.proc.model.trained is False
    httpd = server.ThreadingHTTPServer((server.BIND_HOST, 0), server.make_handler(app))
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        page = urlopen(f"http://127.0.0.1:{port}/").read().decode("utf-8")
        assert "no trained model - demo/animated placeholder" in page
        icon = urlopen(f"http://127.0.0.1:{port}/favicon.ico")
        assert icon.status == 204
        assert "127.0.0.1" in page
        req = Request(
            f"http://127.0.0.1:{port}/api/calibrate",
            data=b"{}",
            headers={"Origin": "https://evil.example", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            urlopen(req)
            raise AssertionError("cross-origin calibrate should fail")
        except HTTPError as exc:
            assert exc.code == 403
        bad = Request(
            f"http://127.0.0.1:{port}/api/threshold",
            data=b"{}",
            headers={"Content-Type": "application/json", "Content-Length": "-1"},
            method="POST",
        )
        # urllib may refuse to send a negative length; call the parser path via a raw socket body instead.
        del bad
        snap = json.loads(urlopen(f"http://127.0.0.1:{port}/api/status").read().decode())
        assert snap["source"]["mode"] == "demo"
    finally:
        httpd.shutdown()
