export async function api<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(
    `/api${path}`,
    body === undefined
      ? undefined
      : {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        },
  );
  const contentType = response.headers.get("content-type") ?? "";
  if (!contentType.includes("application/json"))
    throw new Error(
      "The API did not return JSON. Check that the AgentProof server is running on port 8010.",
    );
  const data = await response.json();
  if (!response.ok) {
    const detail = data.detail;
    throw new Error(
      typeof detail === "string"
        ? detail
        : `Request failed (${response.status}). ${detail ? JSON.stringify(detail) : "Try again after checking the server."}`,
    );
  }
  return data as T;
}
