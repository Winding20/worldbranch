// 后端接口封装。所有错误统一抛出带中文信息的 Error，方便界面直接展示。

const BASE = "";

async function request(path, options = {}) {
  const resp = await fetch(BASE + path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!resp.ok) {
    const body = await resp.json().catch(() => ({}));
    throw new Error(body.error || `请求失败 ${resp.status}`);
  }
  return resp.json();
}

export const api = {
  worlds: () => request("/api/worlds"),
  world: (key) => request(`/api/worlds/${key}`),
  branches: (key) => request(`/api/worlds/${key}/branches`),
  createBranch: (key, payload) =>
    request(`/api/worlds/${key}/branches`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  branchState: (id) => request(`/api/branches/${id}/state`),
  advance: (id, months, precision) =>
    request(`/api/branches/${id}/advance`, {
      method: "POST",
      body: JSON.stringify({ months, precision }),
    }),
  events: (id, params = {}) => {
    const q = new URLSearchParams({ limit: "200", ...params }).toString();
    return request(`/api/branches/${id}/events?${q}`);
  },
  chain: (id, eventId) =>
    request(`/api/branches/${id}/events/${eventId}/chain?depth=6`),
  act: (id, payload) =>
    request(`/api/branches/${id}/actions`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  fork: (id, payload) =>
    request(`/api/branches/${id}/fork`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  snapshots: (id) => request(`/api/branches/${id}/snapshots?limit=120`),
};