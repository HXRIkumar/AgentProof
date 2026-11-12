"""Start SupportDesk and its answer runtime on Mac; never enables paid inference."""

import os
import platform
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODEL = "mlx-community/Qwen3.5-4B-MLX-4bit"
REVISION = "32f3e8ecf65426fc3306969496342d504bfa13f3"
EMBEDDING_REVISION = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"


def local_environment(environment):
    return dict(
        {key: value for key, value in environment.items()
         if not key.startswith("ANSWER_LAB_") and key != "OPENAI_API_KEY"},
        HF_HUB_OFFLINE="1",
        TRANSFORMERS_OFFLINE="1",
        ANSWER_LAB_BASE_URL="http://127.0.0.1:8089/v1",
        ANSWER_LAB_MODEL=MODEL,
        ANSWER_LAB_MODEL_REVISION=REVISION,
        ANSWER_LAB_EMBEDDING_REVISION=EMBEDDING_REVISION,
        ANSWER_LAB_DISABLE_THINKING="true",
        ANSWER_LAB_MAX_TOKENS="1024",
        ANSWER_LAB_ENABLE_PAID="0",
        ANSWER_LAB_API_KEY="",
    )


def unused(port):
    with socket.socket() as sock:
        return sock.connect_ex(("127.0.0.1", port)) != 0


def wait_ready(url, process, seconds):
    until = time.monotonic() + seconds
    while time.monotonic() < until:
        if process.poll() is not None:
            raise RuntimeError("A service exited; inspect its log in artifacts/answer-launcher")
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status == 200:
                    return
        except (OSError, urllib.error.URLError):
            time.sleep(0.4)
    raise RuntimeError("Service startup timed out; inspect artifacts/answer-launcher")


def main():
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        raise SystemExit(
            "This launcher uses MLX on Apple Silicon. Configure an OpenAI-compatible local endpoint on other platforms."
        )
    if not all(unused(port) for port in (8010, 8089)):
        raise SystemExit(
            "Port 8010 or 8089 is already in use. Close the existing AgentProof launcher before starting another."
        )
    from huggingface_hub import snapshot_download
    from huggingface_hub.errors import LocalEntryNotFoundError

    try:
        snapshot = Path(snapshot_download(MODEL, revision=REVISION, local_files_only=True))
    except (LocalEntryNotFoundError, OSError):
        raise SystemExit(
            f"Model is not cached. Download the free weights once with: hf download {MODEL} --revision {REVISION}"
        ) from None
    if not (ROOT / "web/dist/index.html").exists():
        raise SystemExit(
            "Build the web app first: npm --prefix web ci && npm --prefix web run build"
        )
    directory = ROOT / "artifacts/answer-launcher"
    model_path = directory / MODEL
    model_path.parent.mkdir(parents=True, exist_ok=True)
    if model_path.exists() and model_path.resolve() != snapshot.resolve():
        raise SystemExit(
            "Launcher model link points to a different snapshot; inspect it before replacing."
        )
    if not model_path.exists():
        model_path.symlink_to(snapshot, target_is_directory=True)
    env = local_environment(os.environ)
    processes = []
    logs = []

    def stop(*_):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop)
    try:
        log = (directory / "model.log").open("a")
        logs.append(log)
        model = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "mlx_lm",
                "server",
                "--model",
                MODEL,
                "--host",
                "127.0.0.1",
                "--port",
                "8089",
                "--prompt-cache-size",
                "0",
                "--decode-concurrency",
                "1",
                "--prompt-concurrency",
                "1",
            ],
            cwd=directory,
            env=env,
            stdout=log,
            stderr=log,
        )
        processes.append(model)
        print("Loading the local model…", flush=True)
        wait_ready("http://127.0.0.1:8089/v1/models", model, 120)
        log = (directory / "api.log").open("a")
        logs.append(log)
        api = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "agentproof.api:app",
                "--host",
                "127.0.0.1",
                "--port",
                "8010",
            ],
            cwd=ROOT,
            env=env,
            stdout=log,
            stderr=log,
        )
        processes.append(api)
        wait_ready("http://127.0.0.1:8010/api/ready", api, 30)
        webbrowser.open("http://127.0.0.1:8010")
        print(
            "AgentProof SupportDesk is ready at http://127.0.0.1:8010. Keep this window open; Ctrl+C stops its services.",
            flush=True,
        )
        while all(p.poll() is None for p in processes):
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        for process in reversed(processes):
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
        for log in logs:
            log.close()


if __name__ == "__main__":
    main()
