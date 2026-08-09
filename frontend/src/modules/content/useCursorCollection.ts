import { computed, ref, watch, type Ref, type WatchSource } from "vue"

import { ApiError } from "../../api/client"
import { getCursorPage, type CursorPage } from "./api"

export function useCursorCollection<T>(
  firstPage: Ref<CursorPage<T> | undefined>,
  exactPath: string,
  resetKey: WatchSource<unknown>,
  identity: (item: T) => string,
) {
  const additional = ref<T[]>([]) as Ref<T[]>
  const next = ref<string | null>(null)
  const loading = ref(false)
  const error = ref("")

  function reset(): void {
    additional.value = []
    next.value = firstPage.value?.next ?? null
    loading.value = false
    error.value = ""
  }

  watch(resetKey, reset, { immediate: true })
  watch(firstPage, (page) => {
    if (!additional.value.length) next.value = page?.next ?? null
  })

  const items = computed(() => {
    const values = [...(firstPage.value?.results ?? []), ...additional.value]
    return [...new Map(values.map((item) => [identity(item), item])).values()]
  })

  async function loadMore(): Promise<void> {
    if (!next.value || loading.value) return
    const cursor = next.value
    loading.value = true
    error.value = ""
    try {
      const page = await getCursorPage<T>(cursor, exactPath)
      const known = new Set(items.value.map(identity))
      additional.value.push(...page.results.filter((item) => !known.has(identity(item))))
      next.value = page.next
    } catch (reason) {
      error.value = reason instanceof ApiError ? reason.userMessage : "下一页没有加载成功，请重试。"
    } finally {
      loading.value = false
    }
  }

  return { items, next, loading, error, loadMore, reset }
}
