import type {
  SupportConfig,
  SupportDemo,
  SupportDocument,
  SupportTicket,
} from "./supportTypes";
export const SUPPORT_RECORDED = import.meta.env?.VITE_RECORDED_ONLY === "true";
export async function supportApi<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  if (SUPPORT_RECORDED)
    throw new Error(
      "This is a recorded workflow. Run SupportDesk locally to make changes.",
    );
  const response = await fetch(`/api/support${path}`, init);
  const payload = await response.json().catch(() => null);
  if (!response.ok)
    throw new Error(
      typeof payload?.detail === "string"
        ? payload.detail
        : `Request failed (${response.status}).`,
    );
  return payload as T;
}
export function supportPost<T>(path: string, data: unknown) {
  return supportApi<T>(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
}
export async function loadSupport() {
  if (SUPPORT_RECORDED) {
    const response = await fetch(
      `${import.meta.env.BASE_URL}support/demo.json`,
    );
    if (response.status === 404)
      return { config: null, documents: [], tickets: [], demo: null };
    if (!response.ok)
      throw new Error("The recorded support workflow could not be loaded.");
    const demo: SupportDemo = await response.json();
    if (
      demo.format !== "agentproof-support-demo-v1" ||
      !Array.isArray(demo.tickets) ||
      !Array.isArray(demo.documents)
    )
      throw new Error("The recorded workflow has an unsupported format.");
    return {
      config: demo.config,
      documents: demo.documents,
      tickets: demo.tickets,
      demo,
    };
  }
  const [config, documents, tickets] = await Promise.all([
    supportApi<SupportConfig>("/config"),
    supportApi<SupportDocument[]>("/documents"),
    supportApi<SupportTicket[]>("/tickets"),
  ]);
  return { config, documents, tickets, demo: null };
}
export async function filePayload(file: File, maximum = 5 * 1024 * 1024) {
  if (file.size > maximum)
    throw new Error(
      `${file.name} is too large. Maximum ${Math.round(maximum / 1024)} KB.`,
    );
  const content_base64 = await new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",")[1]);
    reader.onerror = () =>
      reject(new Error("The selected file could not be read."));
    reader.readAsDataURL(file);
  });
  return { filename: file.name, content_base64 };
}
export function supportDownload(value: unknown, filename: string) {
  const blob = new Blob([JSON.stringify(value, null, 2)], {
    type: "application/json",
  });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
