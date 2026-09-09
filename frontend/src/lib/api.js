const TOKEN_KEY = "stockpile_token";

export const getToken = () => localStorage.getItem(TOKEN_KEY);
export const setToken = (t) => localStorage.setItem(TOKEN_KEY, t);
export const clearToken = () => localStorage.removeItem(TOKEN_KEY);

export class ApiError extends Error {
  constructor(status, detail) {
    super(typeof detail === "string" ? detail : "Request failed");
    this.status = status;
    this.detail = detail;
  }

  /** Pydantic returns a list of field errors; flatten it into one line. */
  get fieldMessage() {
    if (Array.isArray(this.detail)) {
      return this.detail
        .map((e) => `${e.loc?.at(-1) ?? "field"}: ${e.msg}`)
        .join(", ");
    }
    return this.message;
  }
}

async function request(path, { method = "GET", body, params } = {}) {
  const url = new URL(`/api${path}`, window.location.origin);
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      if (v !== undefined && v !== null && v !== "") url.searchParams.set(k, v);
    }
  }

  const token = getToken();
  const res = await fetch(url, {
    method,
    headers: {
      ...(body ? { "Content-Type": "application/json" } : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });

  if (res.status === 204) return null;

  const payload = await res.json().catch(() => null);
  if (!res.ok) {
    // An expired or revoked token should drop the session rather than leave the
    // app in a half-authenticated state.
    if (res.status === 401 && token) clearToken();
    throw new ApiError(res.status, payload?.detail ?? "Request failed");
  }
  return payload;
}


/**
 * Download a file from an authenticated endpoint.
 *
 * A plain <a href> cannot carry the Authorization header, so the response is
 * fetched, turned into a blob, and handed to a synthetic link. The object URL
 * is revoked afterwards or the blob stays in memory for the life of the page.
 */
export async function downloadFile(path, params) {
  const url = new URL(`/api${path}`, window.location.origin);
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      if (v !== undefined && v !== null && v !== "") url.searchParams.set(k, v);
    }
  }

  const token = getToken();
  const res = await fetch(url, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!res.ok) {
    if (res.status === 401) clearToken();
    throw new ApiError(res.status, "Export failed");
  }

  // Prefer the server's filename from Content-Disposition; it carries the date.
  const disposition = res.headers.get("Content-Disposition") ?? "";
  const match = disposition.match(/filename="([^"]+)"/);
  const filename = match?.[1] ?? path.split("/").pop();

  const blob = await res.blob();
  const href = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = href;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(href);
}

export const api = {
  signup: (email, password) =>
    request("/auth/signup", { method: "POST", body: { email, password } }),
  login: (email, password) =>
    request("/auth/login", { method: "POST", body: { email, password } }),
  me: () => request("/auth/me"),

  listItems: (params) => request("/items", { params }),
  getItem: (id) => request(`/items/${id}`),
  createItem: (body) => request("/items", { method: "POST", body }),
  updateItem: (id, body) => request(`/items/${id}`, { method: "PATCH", body }),
  deleteItem: (id) => request(`/items/${id}`, { method: "DELETE" }),

  listMarketplaces: () => request("/marketplaces"),

  exportItems: (params) => downloadFile("/export/items.csv", params),
  exportSales: () => downloadFile("/export/sales.csv"),

  dashboardSummary: (range) => request("/dashboard/summary", { params: { range } }),
  profitOverTime: (range, bucket) =>
    request("/dashboard/profit-over-time", { params: { range, bucket } }),
  profitByMarketplace: () => request("/dashboard/by-marketplace"),
  inventoryAging: () => request("/dashboard/inventory-aging"),
  topItems: (limit) => request("/dashboard/top-items", { params: { limit } }),

  listSales: (params) => request("/sales", { params }),
  createSale: (body) => request("/sales", { method: "POST", body }),
  voidSale: (id) => request(`/sales/${id}`, { method: "DELETE" }),
};
