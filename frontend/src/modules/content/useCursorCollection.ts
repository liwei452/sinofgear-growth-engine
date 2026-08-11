import { computed, onScopeDispose, ref, shallowRef, watch, type Ref, type WatchSource } from "vue"

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
  const technicalError = shallowRef<unknown>(null)
  let generation = 0
  let disposed = false

  function reset(): void {
    if (disposed) return
    generation += 1
    additional.value = []
    next.value = firstPage.value?.next ?? null
    loading.value = false
    error.value = ""
    technicalError.value = null
  }

  watch(resetKey, reset, { immediate: true })
  watch(firstPage, (page) => {
    if (!disposed && !additional.value.length) next.value = page?.next ?? null
  })

  const items = computed(() => {
    const values = [...(firstPage.value?.results ?? []), ...additional.value]
    return [...new Map(values.map((item) => [identity(item), item])).values()]
  })

  async function loadMore(): Promise<void> {
    if (!next.value || loading.value) return
    const cursor = next.value
    const loadGeneration = generation
    loading.value = true
    error.value = ""
    technicalError.value = null
    try {
      const page = await getCursorPage<T>(cursor, exactPath)
      if (disposed || loadGeneration !== generation) return
      const known = new Set(items.value.map(identity))
      additional.value.push(...page.results.filter((item) => !known.has(identity(item))))
      next.value = page.next
    } catch (reason) {
      if (disposed || loadGeneration !== generation) return
      technicalError.value = reason
      error.value = "下一页没有加载成功，请重试。"
    } finally {
      if (!disposed && loadGeneration === generation) loading.value = false
    }
  }

  onScopeDispose(() => {
    disposed = true
    generation += 1
  })

  return { items, next, loading, error, technicalError, loadMore, reset }
}
