import { request } from "../request";

export interface WebProviderInfo {
  id: string;
  name: string;
  login_url: string;
  models: { id: string; name: string }[];
  status: "not_configured" | "active" | "expired";
  captured_at: string | null;
}

export interface ChromeStartResponse {
  success: boolean;
  pid: number | null;
  message: string;
}

export interface CredentialStatusResponse {
  provider_id: string;
  status: string;
  captured_at: string | null;
  has_cookie: boolean;
  has_bearer: boolean;
  has_session_key: boolean;
}

export const zeroTokenApi = {
  listProviders: () =>
    request<WebProviderInfo[]>("/zero-token/providers"),

  startChrome: (port: number = 9222) =>
    request<ChromeStartResponse>("/zero-token/chrome/start", {
      method: "POST",
      body: JSON.stringify({ port }),
    }),

  getCredentialStatus: (providerId: string) =>
    request<CredentialStatusResponse>(
      `/zero-token/credentials/${encodeURIComponent(providerId)}`,
    ),

  deleteCredential: (providerId: string) =>
    request<{ message: string }>(
      `/zero-token/credentials/${encodeURIComponent(providerId)}`,
      { method: "DELETE" },
    ),
};
