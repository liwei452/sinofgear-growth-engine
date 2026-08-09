import { afterEach, expect, it, vi } from "vitest"

import {
  createConcept,
  knowledgeQueryKeys,
  listAliases,
  listConcepts,
  listEvidence,
  listRelations,
  resolveAlias,
  reviewConcept,
} from "./api"

afterEach(() => {
  vi.unstubAllGlobals()
  document.cookie = "csrftoken=; Max-Age=0; path=/"
})

it("uses exact typed list and resolver endpoints", async () => {
  document.cookie = "csrftoken=csrf-value; path=/"
  const fetchMock = vi.fn()
    .mockImplementation(async () => new Response(JSON.stringify({ results: [] }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }))
  vi.stubGlobal("fetch", fetchMock)

  await listConcepts()
  await listAliases()
  await listRelations()
  await listEvidence()
  fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({
    ambiguous: false, selected: null, candidates: [],
  }), { status: 200, headers: { "Content-Type": "application/json" } }))
  await resolveAlias({ text: "齿轮", language: "zh" })

  expect(fetchMock.mock.calls.map(([path]) => path)).toEqual([
    "/api/v1/knowledge/concepts",
    "/api/v1/knowledge/aliases",
    "/api/v1/knowledge/relations",
    "/api/v1/knowledge/evidence",
    "/api/v1/knowledge/resolve",
  ])
  expect(fetchMock).toHaveBeenLastCalledWith(
    "/api/v1/knowledge/resolve",
    expect.objectContaining({ method: "POST", body: JSON.stringify({ text: "齿轮", language: "zh" }) }),
  )
})

it("creates organization suggestions and sends exact review actions", async () => {
  document.cookie = "csrftoken=csrf-value; path=/"
  const concept = {
    id: "concept-1", scope: "ORGANIZATION", organization: "org-1",
    concept_type: "MATERIAL", code: "STEEL", label_zh: "钢", label_en: "Steel",
    description: "", status: "SUGGESTED", version: 1, evidence: [],
    suggested_by_ai_run_id: null, created_by: 1, reviewed_by: null, reviewed_at: null,
    created_at: "2026-08-09T00:00:00Z", updated_at: "2026-08-09T00:00:00Z",
  }
  const fetchMock = vi.fn().mockImplementation(async () => new Response(JSON.stringify(concept), {
    status: 201,
    headers: { "Content-Type": "application/json" },
  }))
  vi.stubGlobal("fetch", fetchMock)

  expect(knowledgeQueryKeys.concepts()).toEqual(["knowledge", "concepts"])
  await createConcept({
    scope: "ORGANIZATION", concept_type: "MATERIAL", code: "STEEL",
    label_zh: "钢", label_en: "Steel", description: "",
  })
  await reviewConcept("concept-1", "reject", "信息重复")

  expect(fetchMock).toHaveBeenNthCalledWith(
    1,
    "/api/v1/knowledge/concepts",
    expect.objectContaining({ method: "POST" }),
  )
  expect(fetchMock).toHaveBeenNthCalledWith(
    2,
    "/api/v1/knowledge/concepts/concept-1/reject",
    expect.objectContaining({ method: "POST", body: JSON.stringify({ comment: "信息重复" }) }),
  )
})
