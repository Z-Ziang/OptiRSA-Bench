import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest


def _serve(handler_cls):
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def test_hard_timeout_terminates_blocked_http_request():
    from trial.run_openai_compatible_trial import InfrastructureError, _post_chat_hard_timeout

    class SlowHandler(BaseHTTPRequestHandler):
        def do_POST(self):
            time.sleep(2.0)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"choices":[{"message":{"content":"ok"}}]}')
        def log_message(self, *args):
            pass

    server, base = _serve(SlowHandler)
    started = time.monotonic()
    try:
        with pytest.raises(InfrastructureError, match="hard timeout"):
            _post_chat_hard_timeout(
                base, "key", {"model": "m", "messages": []},
                retries=1, request_timeout_seconds=30, hard_timeout_seconds=0.25, backoff_seconds=0,
            )
    finally:
        server.shutdown()
    assert time.monotonic() - started < 1.5


def test_default_large_model_timeout_profile_is_extended_but_bounded():
    from trial.run_openai_compatible_trial import DEFAULT_RUNNER_CONFIG

    assert DEFAULT_RUNNER_CONFIG["request_timeout_seconds"] == 180.0
    assert DEFAULT_RUNNER_CONFIG["request_hard_timeout_seconds"] == 210.0
    assert DEFAULT_RUNNER_CONFIG["case_timeout_seconds"] == 720.0
    assert DEFAULT_RUNNER_CONFIG["request_hard_timeout_seconds"] > DEFAULT_RUNNER_CONFIG["request_timeout_seconds"]
    assert DEFAULT_RUNNER_CONFIG["case_timeout_seconds"] > 2 * DEFAULT_RUNNER_CONFIG["request_hard_timeout_seconds"]


def test_retry_recovers_from_transient_http_failure():
    from trial.run_openai_compatible_trial import _post_chat_hard_timeout

    class FlakyHandler(BaseHTTPRequestHandler):
        calls = 0
        def do_POST(self):
            type(self).calls += 1
            if type(self).calls == 1:
                self.send_response(503)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"choices":[{"message":{"content":"ok"}}]}')
        def log_message(self, *args):
            pass

    server, base = _serve(FlakyHandler)
    try:
        response = _post_chat_hard_timeout(
            base, "key", {"model": "m", "messages": []},
            retries=2, request_timeout_seconds=5, hard_timeout_seconds=2, backoff_seconds=0,
        )
    finally:
        server.shutdown()
    assert response["choices"][0]["message"]["content"] == "ok"
    assert FlakyHandler.calls == 2


def test_resume_loads_terminal_trial_record(tmp_path):
    from trial.run_openai_compatible_trial import _load_resume_record

    target = tmp_path / "case"
    target.mkdir()
    record = {"execution_status": "SUCCESS", "case_id": "X1_000001", "track": "llm"}
    (target / "trial_record.json").write_text(json.dumps(record), encoding="utf-8")
    assert _load_resume_record(target, resume=True) == record
    assert _load_resume_record(target, resume=False) is None


def test_extra_body_rejects_reserved_keys():
    from trial.run_openai_compatible_trial import _load_extra_body
    with pytest.raises(ValueError, match="reserved"):
        _load_extra_body('{"model":"other"}')
    assert _load_extra_body('{"enable_thinking":false}') == {"enable_thinking": False}


def test_runner_cli_does_not_accept_tracks_option():
    from trial.run_openai_compatible_trial import main
    with pytest.raises(SystemExit):
        main(["--producer-dir", ".", "--dataset-dir", ".", "--tracks", "llm"])
