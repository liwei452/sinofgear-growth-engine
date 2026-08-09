import { queryOptions } from "@tanstack/vue-query"

import { apiRequest } from "../../api/client"

export type CurrentUser = {
  user: { id: number; username: string }
  organization: { id: string; name: string; slug: string }
  membership: { id: string; role: string; status: string }
}

export type LoginCredentials = { username: string; password: string }

export async function getCurrentUser(): Promise<CurrentUser> {
  const user = await apiRequest<CurrentUser>("/api/v1/auth/me")
  if (!user) throw new Error("当前用户响应为空。")
  return user
}

export function currentUserQueryOptions() {
  return queryOptions({
    queryKey: ["auth", "me"] as const,
    queryFn: getCurrentUser,
    retry: false,
    staleTime: 30_000,
  })
}

export async function login(credentials: LoginCredentials): Promise<void> {
  await apiRequest("/api/v1/auth/login", { method: "POST", body: credentials })
}

export async function logout(): Promise<void> {
  await apiRequest("/api/v1/auth/logout", { method: "POST" })
}
