import { QueryClient } from "@tanstack/vue-query"

export function createQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        refetchOnWindowFocus: false,
        retry: 1,
        staleTime: 30_000,
      },
      mutations: { retry: false },
    },
  })
}

export const queryClient = createQueryClient()
