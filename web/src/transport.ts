const ARCHIVE_IDS = new Set([
  "challenge-v02", "challenge-v01", "original-v02", "original-v01", "independent-v03",
]);

function projectBase(base: string) {
  if (!/^\/(?:[A-Za-z0-9_-]+\/)*$/.test(base))
    throw new Error("Recorded evidence requires an absolute project base path.");
  return base;
}

export function recordedResource(path: string, body: unknown, base: string) {
  if (body !== undefined)
    throw new Error("Recorded evidence is read-only. Run the local application to execute experiments.");
  if (path === "/evidence") return `${projectBase(base)}evidence/catalog.json`;
  const match = /^\/evidence\/([a-z0-9-]+)$/.exec(path);
  if (!match || !ARCHIVE_IDS.has(match[1]))
    throw new Error("This recorded-only build has no workspace API.");
  return `${projectBase(base)}evidence/${match[1]}.json`;
}

export function recordedDownload(archive: { id: string; sha256: string; download_url: string }, base: string) {
  if (!ARCHIVE_IDS.has(archive.id) || !/^[0-9a-f]{64}$/.test(archive.sha256)
      || archive.download_url !== `evidence/raw/${archive.sha256}.json`)
    throw new Error("Invalid recorded download path.");
  return `${projectBase(base)}${archive.download_url}`;
}

export function createTransport(recordedOnly: boolean, base: string, fetcher?: typeof fetch) {
  return async function api<T>(path: string, body?: unknown, signal?: AbortSignal): Promise<T> {
    const url = recordedOnly ? recordedResource(path, body, base) : `/api${path}`;
    const response = await (fetcher ?? fetch)(url, body === undefined ? { signal } : {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body), signal,
    });
    const contentType = response.headers.get("content-type") ?? "";
    if (!contentType.includes("application/json"))
      throw new Error(recordedOnly
        ? "Recorded evidence is missing from this build. Rebuild the static distribution."
        : "The API did not return JSON. Check that the AgentProof server is running on port 8010.");
    const data = await response.json();
    if (!response.ok) {
      const detail = data.detail;
      throw new Error(typeof detail === "string" ? detail
        : `Request failed (${response.status}). ${detail ? JSON.stringify(detail) : "Try again after checking the server."}`);
    }
    return data as T;
  };
}
