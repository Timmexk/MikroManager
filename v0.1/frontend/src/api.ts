export class ApiError extends Error {
  constructor(message: string, public status: number) {
    super(message);
  }
}

async function req<T = any>(method: string, url: string, body?: unknown): Promise<T> {
  let res: Response;
  try {
    res = await fetch(url, {
      method,
      credentials: "same-origin",
      headers: body === undefined ? undefined : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError("TikControl is niet bereikbaar", 0);
  }
  if (res.status === 401 && !url.endsWith("/login")) {
    window.dispatchEvent(new Event("tc-unauthorized"));
  }
  const text = await res.text();
  const data = text ? safeJson(text) : null;
  if (!res.ok) throw new ApiError(data?.detail || `Fout ${res.status}`, res.status);
  return data as T;
}

function safeJson(text: string) {
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

export const api = {
  get: <T = any>(url: string) => req<T>("GET", url),
  post: <T = any>(url: string, body: unknown = {}) => req<T>("POST", url, body),
  patch: <T = any>(url: string, body: unknown) => req<T>("PATCH", url, body),
  del: <T = any>(url: string) => req<T>("DELETE", url),
};
