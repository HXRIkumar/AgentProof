"""Mountable answer API; no arbitrary file or model-endpoint input from the browser."""

import json
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException

from .engine import AnswerService, RuntimeBusy
from .models import AnswerRequest


def create_router(service: AnswerService, reports_dir: Path | None = None) -> APIRouter:
    router = APIRouter(prefix="/api/answers", tags=["Answer Lab"])
    directory = Path(reports_dir) if reports_dir is not None else Path("reports/answer-lab")

    @router.get("/config")
    def configuration():
        return service.public_config()

    @router.post("/run")
    def run(request: AnswerRequest):
        try:
            return service.run(request)
        except RuntimeBusy as exc:
            raise HTTPException(409, str(exc)) from None
        except ValueError:
            raise HTTPException(422, "Answer input could not be processed") from None

    @router.get("/runs")
    def recent():
        return service.store.recent()

    @router.get("/runs/{run_id}")
    def saved(run_id: str):
        try:
            return service.store.get(run_id)
        except KeyError:
            raise HTTPException(404, "Answer run not found") from None

    def read_report(path):
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 30_000_000:
            raise ValueError("Invalid report")
        data = json.loads(path.read_text())
        if not isinstance(data, dict) or not isinstance(data.get("summary"), dict):
            raise TypeError("Invalid report")
        return data

    @router.get("/reports")
    def reports():
        items = []
        for path in sorted(directory.glob("*.json"), reverse=True):
            try:
                data = read_report(path)
            except (OSError, ValueError, TypeError, UnicodeError):
                continue
            items.append(
                {
                    "id": path.stem,
                    "title": data.get("title", path.stem),
                    "model": data.get("model", "unrecorded"),
                    "created_at": data.get("created_at"),
                    "summary": data["summary"],
                }
            )
        return items

    @router.get("/reports/{report_id}")
    def report(report_id: str):
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", report_id):
            raise HTTPException(404, "Report not found")
        try:
            return read_report(directory / (report_id + ".json"))
        except (OSError, ValueError, TypeError, UnicodeError):
            raise HTTPException(404, "Report not found") from None

    cache_directory = directory.with_name("answers-cache")

    @router.get("/cache-reports")
    def cache_reports():
        items = []
        for path in sorted(cache_directory.glob("*.json"), reverse=True):
            try:
                data = read_report(path)
            except (OSError, ValueError, UnicodeError, RecursionError):
                continue
            if data.get("format") != "answer-cache-probe-v1":
                continue
            items.append(
                {
                    "id": path.stem,
                    "title": "Exact replay and semantic cache study",
                    "model": data.get("configuration", {})
                    .get("provider", {})
                    .get("model", "unrecorded"),
                    "created_at": data.get("created_at"),
                    "summary": data["summary"],
                }
            )
        return items

    @router.get("/cache-reports/{report_id}")
    def cache_report(report_id: str):
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", report_id):
            raise HTTPException(404, "Report not found")
        try:
            data = read_report(cache_directory / (report_id + ".json"))
            if data.get("format") != "answer-cache-probe-v1":
                raise ValueError("Invalid cache report")
            return data
        except (OSError, ValueError, UnicodeError, RecursionError):
            raise HTTPException(404, "Report not found") from None

    return router
