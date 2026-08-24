// =====================================================
// ORBITAL GUARDIAN — API client + auth session helpers
// =====================================================

const DEFAULT_API_URL = "http://127.0.0.1:8000";

export function getApiUrl() {
  return localStorage.getItem("og_api_url") || DEFAULT_API_URL;
}

export function setApiUrl(url) {
  localStorage.setItem("og_api_url", url.replace(/\/+$/, ""));
}

// -----------------------------------------------------
// SESSION (Firebase ID token, with legacy fallback)
// -----------------------------------------------------

const TOKEN_KEY = "og_access_token";
const REFRESH_KEY = "og_refresh_token";
const USER_KEY = "og_user";

let firebaseAuth = null;

export function setFirebaseAuth(authInstance) {
  firebaseAuth = authInstance;
}

async function currentIdToken() {
  if (firebaseAuth?.currentUser) {
    // getIdToken() auto-refreshes expired tokens.
    try {
      return await firebaseAuth.currentUser.getIdToken();
    } catch {
      return null;
    }
  }

  return localStorage.getItem(TOKEN_KEY);
}

export async function getBearerToken() {
  return currentIdToken();
}

export function getUser() {
  try {
    return JSON.parse(localStorage.getItem(USER_KEY) || "null");
  } catch {
    return null;
  }
}

export function isLoggedIn() {
  if (firebaseAuth?.currentUser) return true;

  return Boolean(localStorage.getItem(TOKEN_KEY));
}

export function hasRole(minimum) {
  const order = { VIEWER: 0, ANALYST: 1, ADMIN: 2 };
  const user = getUser();
  if (!user) return false;
  return (order[user.role] ?? -1) >= (order[minimum] ?? 0);
}

export function saveSession(data) {
  localStorage.setItem(USER_KEY, JSON.stringify(data.user));

  // Legacy local-auth tokens (unused with Firebase).
  if (data.access_token) {
    localStorage.setItem(TOKEN_KEY, data.access_token);
    localStorage.setItem(REFRESH_KEY, data.refresh_token);
  }
}

export function clearSession() {
  localStorage.removeItem(USER_KEY);

  if (!firebaseAuth?.currentUser) {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(REFRESH_KEY);
  }
}

async function tryRefresh() {
  const refreshToken = localStorage.getItem(REFRESH_KEY);
  if (!refreshToken) return false;

  try {
    const response = await fetch(`${getApiUrl()}/auth/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refreshToken }),
    });

    if (!response.ok) return false;

    const data = await response.json();

    // Keep refresh rotation: server revoked old token.
    saveSession(data);

    return true;
  } catch {
    return false;
  }
}

// -----------------------------------------------------
// FETCH WRAPPER
// -----------------------------------------------------

export async function api(path, options = {}, retry = true) {
  const headers = { ...(options.headers || {}) };

  if (options.body && !headers["Content-Type"]) {
    headers["Content-Type"] = "application/json";
  }

  const token = await currentIdToken();

  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }

  let response;

  try {
    response = await fetch(`${getApiUrl()}${path}`, { ...options, headers });
  } catch {
    throw new Error(
      "Backend unreachable. Is the API server running at " +
        getApiUrl() +
        " ?",
    );
  }

  // Access token expired once -> refresh and retry a single time.
  if (response.status === 401 && retry && localStorage.getItem(REFRESH_KEY)) {
    const refreshed = await tryRefresh();

    if (refreshed) {
      return api(path, options, false);
    }

    clearSession();
  }

  if (!response.ok) {
    let detail = `Request failed (${response.status})`;

    try {
      const body = await response.json();

      if (body.detail) {
        detail =
          typeof body.detail === "string"
            ? body.detail
            : JSON.stringify(body.detail);
      }
    } catch {
      /* non-JSON error */
    }

    const error = new Error(detail);
    error.status = response.status;
    throw error;
  }

  if (response.status === 204) return null;

  return response.json();
}
