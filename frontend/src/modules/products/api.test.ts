import { afterEach, expect, it, vi } from "vitest"

import { ApiError } from "../../api/client"
import {
  createProduct,
  getProduct,
  getProductPage,
  patchProduct,
  productQueryKeys,
  safeProductPageUrl,
} from "./api"

afterEach(() => {
  vi.unstubAllGlobals()
  document.cookie = "csrftoken=; Max-Age=0; path=/"
})

it("accepts only same-origin product pagination URLs", () => {
  expect(safeProductPageUrl("/api/v1/products?cursor=abc&page_size=20")).toBe(
    "/api/v1/products?cursor=abc&page_size=20",
  )
  expect(safeProductPageUrl(`${window.location.origin}/api/v1/products?cursor=back`)).toBe(
    "/api/v1/products?cursor=back",
  )
  for (const unsafe of [
    "https://evil.example/api/v1/products?cursor=steal",
    "//evil.example/api/v1/products",
    "/api/v1/auth/me?cursor=wrong-path",
    "not a valid page url",
  ]) {
    expect(safeProductPageUrl(unsafe)).toBeNull()
  }
})

it("rejects an external page before it can reach fetch", async () => {
  const fetchMock = vi.fn()
  vi.stubGlobal("fetch", fetchMock)

  await expect(getProductPage("https://evil.example/api/v1/products")).rejects.toBeInstanceOf(ApiError)
  expect(fetchMock).not.toHaveBeenCalled()
})

it("uses stable query keys and preserves ETag for create, detail, and patch", async () => {
  document.cookie = "csrftoken=csrf-value; path=/"
  const product = { id: "product-1", name_en: "Helical Gear", version: 2 }
  const fetchMock = vi.fn()
    .mockResolvedValueOnce(new Response(JSON.stringify(product), {
      status: 200,
      headers: { "Content-Type": "application/json", ETag: '"2"' },
    }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ ...product, version: 1 }), {
      status: 201,
      headers: { "Content-Type": "application/json", ETag: '"1"' },
    }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ ...product, version: 3 }), {
      status: 200,
      headers: { "Content-Type": "application/json", ETag: '"3"' },
    }))
  vi.stubGlobal("fetch", fetchMock)

  expect(productQueryKeys.detail("product-1")).toEqual(["products", "detail", "product-1"])
  await expect(getProduct("product-1")).resolves.toMatchObject({ etag: '"2"' })
  await expect(createProduct({ name_en: "Helical Gear" } as never)).resolves.toMatchObject({ etag: '"1"' })
  await expect(patchProduct("product-1", { name_en: "Updated" }, '"2"')).resolves.toMatchObject({ etag: '"3"' })
  expect(fetchMock).toHaveBeenNthCalledWith(
    3,
    "/api/v1/products/product-1",
    expect.objectContaining({
      method: "PATCH",
      headers: expect.objectContaining({ "if-match": '"2"' }),
    }),
  )
})
