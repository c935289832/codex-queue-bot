#!/usr/bin/env python3
"""Isolated native Codex runner; smoke uses a loopback Responses fixture only."""
import argparse
import contextlib
import http.server
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_MODEL = "codex-ci-fixture"
FIXTURE_TOKEN = "ci-fixture-no-real-key"

def provider_config(base_url, model):
    return f'''model = {json.dumps(model)}
model_provider = "anyrouter_keepalive"
approval_policy = "never"
sandbox_mode = "read-only"
web_search = "disabled"
disable_response_storage = true

[model_providers.anyrouter_keepalive]
name = "AnyRouter Codex keepalive"
base_url = {json.dumps(base_url)}
env_key = "ANYROUTER_API_KEY"
wire_api = "responses"
requires_openai_auth = false
supports_websockets = false
request_max_retries = 0
stream_max_retries = 0

[shell_environment_policy]
inherit = "none"
'''

def summary(text):
    print(text)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as stream:
            stream.write(text + "\n")

def invoke(base_url, model, token, timeout=180):
    binary = shutil.which("codex")
    if not binary:
        print("ERROR: Codex CLI is not installed.", file=sys.stderr)
        return 127
    parent = Path(os.environ.get("RUNNER_TEMP", tempfile.gettempdir())).resolve()
    with tempfile.TemporaryDirectory(prefix="codex-keepalive-", dir=parent) as name:
        work = Path(name).resolve()
        assert work.parent == parent
        home = work / "home"
        codex_home = home / ".codex"
        codex_home.mkdir(parents=True, mode=0o700)
        config = codex_home / "config.toml"
        config.write_text(provider_config(base_url, model), encoding="utf-8")
        config.chmod(0o600)
        prompts = work / "prompts.txt"
        prompts.write_text("Reply with exactly: OK\n", encoding="utf-8")
        allowed = {"PATH", "SystemRoot", "SYSTEMROOT", "COMSPEC", "PATHEXT", "WINDIR", "LANG", "LC_ALL", "TERM"}
        env = {key: value for key, value in os.environ.items() if key in allowed}
        env.update({
            "HOME": str(home), "USERPROFILE": str(home), "CODEX_HOME": str(codex_home),
            "CODEX_BIN": binary, "ANYROUTER_API_KEY": token,
            "PROMPTS_FILE": str(prompts), "LOG_FILE": str(work / "healthcheck.log"),
            "REQUEST_TIMEOUT_SEC": str(timeout),
            "TMPDIR": str(work), "TMP": str(work), "TEMP": str(work),
        })
        try:
            result = subprocess.run(
                ["bash", str(ROOT / "codex-healthcheck.sh"), "--once"],
                cwd=work, env=env, text=True, encoding="utf-8", errors="replace",
                capture_output=True, timeout=timeout + 20,
            )
        except subprocess.TimeoutExpired:
            print("ERROR: healthcheck adapter exceeded its timeout.", file=sys.stderr)
            return 124
        def redact(value):
            return value.replace(token, "[REDACTED]") if token else value
        print(redact(result.stdout), end="")
        print(redact(result.stderr), end="", file=sys.stderr)
        if result.returncode:
            log = work / "healthcheck.log"
            if log.is_file():
                print(redact("\n".join(log.read_text(encoding="utf-8", errors="replace").splitlines()[-40:])), file=sys.stderr)
        return result.returncode

@contextlib.contextmanager
def local_responses_fixture():
    observed = []
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
            valid = (self.path == "/v1/responses" and body.get("model") == FIXTURE_MODEL
                     and self.headers.get("Authorization") == "Bearer " + FIXTURE_TOKEN)
            observed.append({"path": self.path, "model": body.get("model"), "valid": valid})
            if not valid:
                self.send_error(400, "Unexpected fixture request")
                return
            message = {"id": "msg_fixture", "type": "message", "status": "completed", "role": "assistant",
                       "content": [{"type": "output_text", "text": "CODEX_SMOKE_OK", "annotations": []}]}
            response = {"id": "resp_fixture", "object": "response", "created_at": int(time.time()),
                        "status": "completed", "model": FIXTURE_MODEL, "output": [message],
                        "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}}
            events = [
                {"type": "response.created", "response": {**response, "status": "in_progress", "output": []}},
                {"type": "response.output_item.added", "output_index": 0,
                 "item": {**message, "status": "in_progress", "content": []}},
                {"type": "response.content_part.added", "item_id": "msg_fixture", "output_index": 0,
                 "content_index": 0, "part": {"type": "output_text", "text": "", "annotations": []}},
                {"type": "response.output_text.delta", "item_id": "msg_fixture", "output_index": 0,
                 "content_index": 0, "delta": "CODEX_SMOKE_OK"},
                {"type": "response.output_text.done", "item_id": "msg_fixture", "output_index": 0,
                 "content_index": 0, "text": "CODEX_SMOKE_OK"},
                {"type": "response.output_item.done", "output_index": 0, "item": message},
                {"type": "response.completed", "response": response},
            ]
            payload = "".join(f"event: {event['type']}\ndata: {json.dumps(event)}\n\n" for event in events).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/v1", observed
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

def main():
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--smoke-test", action="store_true")
    mode.add_argument("--live", action="store_true")
    args = parser.parse_args()
    if args.smoke_test:
        with local_responses_fixture() as (base_url, observed):
            code = invoke(base_url, FIXTURE_MODEL, FIXTURE_TOKEN, timeout=60)
        if code or not observed or not all(item["valid"] for item in observed):
            summary(f"SMOKE FAILED: CLI exit={code}; loopback requests={json.dumps(observed)}")
            return code or 1
        summary("SMOKE PASS: real Codex CLI completed a loopback Responses request. No real AnyRouter API was called; no provider quota consumed.")
        return 0
    required = ["ANYROUTER_API_KEY", "ANYROUTER_BASE_URL", "CODEX_MODEL"]
    missing = [key for key in required if not os.environ.get(key, "").strip()]
    if missing:
        summary("CONFIGURATION REQUIRED: " + ", ".join(missing) + ". No real API request was sent.")
        return 2
    token, base_url, model = [os.environ[key].strip() for key in required]
    parsed = urlsplit(base_url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        summary("CONFIGURATION ERROR: ANYROUTER_BASE_URL must be the trusted HTTPS API base URL without credentials, query or fragment.")
        return 2
    if any(char in token + model for char in "\r\n\x00"):
        summary("CONFIGURATION ERROR: API key and model must be single-line values.")
        return 2
    code = invoke(base_url.rstrip("/"), model, token)
    summary("LIVE PASS: Codex returned a non-empty final response." if code == 0 else f"LIVE FAILED: Codex healthcheck exited {code}.")
    return code

if __name__ == "__main__":
    raise SystemExit(main())
