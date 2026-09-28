import axios, { AxiosError, AxiosRequestConfig } from "axios";

export const ACCESS_TOKEN_KEY = "ops-dashboard.auth.access";
export const REFRESH_TOKEN_KEY = "ops-dashboard.auth.refresh";

const LEGACY_TOKEN_KEY = "ops-dashboard.auth.token";

export const apiClient = axios.create({
  baseURL: "/api/v1",
  headers: { "Content-Type": "application/json" },
});

function clearTokens(): void {
  localStorage.removeItem(ACCESS_TOKEN_KEY);
  localStorage.removeItem(REFRESH_TOKEN_KEY);
  localStorage.removeItem(LEGACY_TOKEN_KEY);
}

function redirectToLogin(): void {
  clearTokens();
  if (globalThis.location.pathname !== "/login") {
    globalThis.location.assign("/login");
  }
}

apiClient.interceptors.request.use((config) => {
  const token = localStorage.getItem(ACCESS_TOKEN_KEY);
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

let refreshPromise: Promise<string> | null = null;

async function attemptRefresh(): Promise<string> {
  if (refreshPromise) {
    return refreshPromise;
  }
  const refreshToken = localStorage.getItem(REFRESH_TOKEN_KEY);
  if (!refreshToken) {
    throw new Error("No refresh token available");
  }
  refreshPromise = axios
    .post<{ access_token: string; refresh_token: string }>("/api/v1/auth/refresh", {
      refresh_token: refreshToken,
    })
    .then((response) => {
      const newAccess = response.data.access_token;
      const newRefresh = response.data.refresh_token;
      localStorage.setItem(ACCESS_TOKEN_KEY, newAccess);
      if (newRefresh) {
        localStorage.setItem(REFRESH_TOKEN_KEY, newRefresh);
      }
      return newAccess;
    })
    .finally(() => {
      refreshPromise = null;
    });
  return refreshPromise;
}

apiClient.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const status = error.response?.status;
    const config = error.config as (AxiosRequestConfig & { _retry?: boolean }) | undefined;

    if (!config || status !== 401) {
      throw error;
    }

    const isAuthEndpoint = config.url?.includes("/auth/") ?? false;

    if (config._retry || isAuthEndpoint) {
      redirectToLogin();
      throw error;
    }

    config._retry = true;
    try {
      const newAccess = await attemptRefresh();
      config.headers = {
        ...(config.headers ?? {}),
        Authorization: `Bearer ${newAccess}`,
      };
      return apiClient.request(config);
    } catch {
      redirectToLogin();
      throw error;
    }
  },
);
