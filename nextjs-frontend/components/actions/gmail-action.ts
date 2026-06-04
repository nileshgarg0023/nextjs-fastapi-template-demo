"use server";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";

const apiBaseUrl = process.env.API_BASE_URL || "http://localhost:8000";

export type GmailStatus = {
  connected: boolean;
  email_address?: string | null;
  categories?: string[];
};

export type GmailTriageState = {
  result?: string;
  message?: string;
};

export async function fetchGmailStatus(): Promise<GmailStatus> {
  const token = await getAccessToken();
  if (!token) {
    return { connected: false };
  }

  const response = await fetch(`${apiBaseUrl}/emails/gmail/status`, {
    headers: { Authorization: `Bearer ${token}` },
    cache: "no-store",
  });

  if (!response.ok) {
    return { connected: false };
  }

  return response.json();
}

export async function connectGmail() {
  const token = await getAccessToken();
  if (!token) {
    redirect("/login");
  }

  const response = await fetch(`${apiBaseUrl}/emails/gmail/connect-url`, {
    headers: { Authorization: `Bearer ${token}` },
    cache: "no-store",
  });

  if (!response.ok) {
    const error = await response.json().catch(() => null);
    const message =
      error?.detail || "Unable to start Gmail authorization.";
    redirect(`/dashboard/gmail?error=${encodeURIComponent(message)}`);
  }

  const data = (await response.json()) as { url: string };
  redirect(data.url);
}

export async function triageConnectedGmail(
  prevState: GmailTriageState,
  formData: FormData,
): Promise<GmailTriageState> {
  const token = await getAccessToken();
  if (!token) {
    return { message: "Please sign in again." };
  }

  const response = await fetch(`${apiBaseUrl}/emails/gmail/triage-connected`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      search_query: formData.get("search_query") || "newer_than:1d",
      max_results: Number(formData.get("max_results") || 50),
      dry_run: formData.get("dry_run") === "on",
      user_focus: formData.get("user_focus"),
    }),
  });

  const data = await response.json();
  if (!response.ok) {
    return { message: data.detail || "Unable to sort Gmail." };
  }

  return { result: data.result };
}

async function getAccessToken() {
  return (await cookies()).get("accessToken")?.value;
}
