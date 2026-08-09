import { defineComponent, ref } from "vue"
import { render, screen } from "@testing-library/vue"
import userEvent from "@testing-library/user-event"
import { afterEach, expect, it, vi } from "vitest"

import type { CursorPage } from "./api"
import { useCursorCollection } from "./useCursorCollection"

type Item = { id: string; label: string }

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => { resolve = done })
  return { promise, resolve }
}

const Harness = defineComponent({
  setup() {
    const resetKey = ref("org-1:old-filter")
    const firstPage = ref<CursorPage<Item>>({
      next: "/api/v1/master-contents?cursor=old",
      previous: null,
      results: [{ id: "old-first", label: "old first" }],
    })
    const collection = useCursorCollection(
      firstPage, "/api/v1/master-contents", resetKey, (item) => item.id,
    )
    function resetOrganizationAndFilter(): void {
      firstPage.value = {
        next: "/api/v1/master-contents?cursor=new",
        previous: null,
        results: [{ id: "new-first", label: "new first" }],
      }
      resetKey.value = "org-2:new-filter"
    }
    return { ...collection, resetOrganizationAndFilter }
  },
  template: `
    <div>
      <p data-testid="items">{{ items.map(item => item.label).join('|') }}</p>
      <p data-testid="next">{{ next ?? 'end' }}</p>
      <p v-if="error" role="alert">{{ error }}</p>
      <button type="button" @click="loadMore">{{ loading ? 'loading' : 'load' }}</button>
      <button type="button" @click="resetOrganizationAndFilter">reset key</button>
    </div>
  `,
})

afterEach(() => { vi.unstubAllGlobals() })

it("ignores an old page success after a new organization and filter generation finishes", async () => {
  const oldPage = deferred<Response>()
  vi.stubGlobal("fetch", vi.fn(async (path: string) => {
    if (path.includes("cursor=old")) return oldPage.promise
    return new Response(JSON.stringify({
      next: null, previous: null, results: [{ id: "new-second", label: "new second" }],
    }), { status: 200, headers: { "Content-Type": "application/json" } })
  }))
  const user = userEvent.setup()
  render(Harness)
  await user.click(screen.getByRole("button", { name: "load" }))
  await user.click(screen.getByRole("button", { name: "reset key" }))
  await user.click(await screen.findByRole("button", { name: "load" }))
  await screen.findByText("new first|new second")

  oldPage.resolve(new Response(JSON.stringify({
    next: "/api/v1/master-contents?cursor=stale", previous: null,
    results: [{ id: "old-second", label: "old second" }],
  }), { status: 200, headers: { "Content-Type": "application/json" } }))
  await oldPage.promise
  await new Promise((resolve) => setTimeout(resolve, 0))

  expect(screen.getByTestId("items")).toHaveTextContent("new first|new second")
  expect(screen.getByTestId("items")).not.toHaveTextContent("old second")
  expect(screen.getByTestId("next")).toHaveTextContent("end")
  expect(screen.getByRole("button", { name: "load" })).toBeEnabled()
  expect(screen.queryByRole("alert")).not.toBeInTheDocument()
})

it("ignores an old page error and finally after the new generation starts", async () => {
  const oldPage = deferred<Response>()
  vi.stubGlobal("fetch", vi.fn(async (path: string) => {
    if (path.includes("cursor=old")) return oldPage.promise
    return new Response(JSON.stringify({
      next: "/api/v1/master-contents?cursor=newer", previous: null,
      results: [{ id: "new-second", label: "new second" }],
    }), { status: 200, headers: { "Content-Type": "application/json" } })
  }))
  const user = userEvent.setup()
  render(Harness)
  await user.click(screen.getByRole("button", { name: "load" }))
  await user.click(screen.getByRole("button", { name: "reset key" }))
  await user.click(await screen.findByRole("button", { name: "load" }))
  await screen.findByText("new first|new second")

  oldPage.resolve(new Response(JSON.stringify({ detail: "stale error" }), {
    status: 503, headers: { "Content-Type": "application/json" },
  }))
  await oldPage.promise
  await new Promise((resolve) => setTimeout(resolve, 0))

  expect(screen.queryByRole("alert")).not.toBeInTheDocument()
  expect(screen.getByTestId("items")).toHaveTextContent("new first|new second")
  expect(screen.getByTestId("next")).toHaveTextContent("cursor=newer")
  expect(screen.getByRole("button", { name: "load" })).toBeEnabled()
})
