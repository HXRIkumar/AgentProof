import { createTransport, recordedDownload } from "./transport";
import type { RecordedEvidence } from "./types";

export const RECORDED_ONLY = import.meta.env.VITE_RECORDED_ONLY === "true";
export const api = createTransport(RECORDED_ONLY, import.meta.env.BASE_URL);
export const evidenceDownloadUrl = (archive: RecordedEvidence) => RECORDED_ONLY
  ? recordedDownload(archive, import.meta.env.BASE_URL)
  : archive.download_url;
