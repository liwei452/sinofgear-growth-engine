import { readFileSync } from "node:fs"
import { resolve } from "node:path"

import { describe, expect, expectTypeOf, it } from "vitest"
import openapi from "./generated/openapi.json"
import "./generated/schema"
import type { components, paths } from "./generated/schema"

type RequiredPaths =
  | "/api/v1/knowledge/concepts"
  | "/api/v1/knowledge/relations"
  | "/api/v1/products"
  | "/api/v1/assets"
  | "/api/v1/campaigns"
  | "/api/v1/content-briefs"
  | "/api/v1/master-contents"
  | "/api/v1/platform-contents"
  | "/api/v1/publish-tasks"
  | "/api/v1/tracking-links"
  | "/api/v1/short-links"
  | "/api/v1/jobs"
  | "/api/v1/auth/login"

describe("generated API contract", () => {
  it("ships a non-empty runtime schema artifact with required paths and components", () => {
    const source = readFileSync(resolve(process.cwd(), "src", "api", "generated", "schema.ts"), "utf8")
    const serializedOpenAPI = JSON.stringify(openapi)
    expect(source.length).toBeGreaterThan(100_000)
    expect(Object.keys(openapi.paths)).toEqual(expect.arrayContaining([
      "/api/v1/knowledge/concepts",
      "/api/v1/products",
      "/api/v1/publish-tasks",
      "/api/v1/tracking-links",
    ]))
    expect(Object.keys(openapi.components.schemas)).toEqual(expect.arrayContaining([
      "AIRun",
      "ApiError",
      "MasterContent",
      "PublishTask",
    ]))
    expect(serializedOpenAPI.length).toBeGreaterThan(100_000)
    expect(openapi).not.toHaveProperty("servers")
    expect(`${source}\n${serializedOpenAPI}`).not.toMatch(/Generated (?:at|on):/i)
    expect(`${source}\n${serializedOpenAPI}`).not.toMatch(
      /(?:[A-Z]:\\Users\\|\/home\/|localhost|127\.0\.0\.1|password=|api[_-]?key=|bearer\s+[A-Za-z0-9])/i,
    )

    const schemaNames = new Set(Object.keys(openapi.components.schemas))
    const visit = (value: unknown): void => {
      if (Array.isArray(value)) {
        value.forEach(visit)
      } else if (value && typeof value === "object") {
        const node = value as Record<string, unknown>
        if (typeof node.$ref === "string" && node.$ref.startsWith("#/components/schemas/")) {
          expect(schemaNames.has(node.$ref.split("/").at(-1) ?? "")).toBe(true)
        }
        Object.values(node).forEach(visit)
      }
    }
    visit(openapi)
    for (const pathItem of Object.values(openapi.paths)) {
      for (const operation of Object.values(pathItem)) {
        if (operation && typeof operation === "object" && "tags" in operation) {
          expect(operation.tags).not.toEqual(["api"])
        }
      }
    }
  })

  it("contains every Phase A resource path", () => {
    expectTypeOf<Exclude<RequiredPaths, keyof paths>>().toEqualTypeOf<never>()
  })

  it("exposes the recoverable mutation error envelope", () => {
    expectTypeOf<components["schemas"]["ApiError"]>().toMatchTypeOf<{
      code: string
      message: string
      recovery_action: string
    }>()
  })

  it("keeps current-head flags boolean in generated response types", () => {
    expectTypeOf<components["schemas"]["MasterContent"]["is_current_head"]>().toEqualTypeOf<boolean>()
    expectTypeOf<components["schemas"]["PlatformContent"]["is_current_head"]>().toEqualTypeOf<boolean>()
  })

  it("keeps nullable AI JSON fields nullable in generated response types", () => {
    expectTypeOf<components["schemas"]["AIRun"]["output_json"]>().toMatchTypeOf<object | null>()
    expectTypeOf<components["schemas"]["AIRun"]["human_correction"]>().toMatchTypeOf<object | null>()
    expect(openapi.components.schemas.AIRun.properties.output_json.nullable).toBe(true)
    expect(openapi.components.schemas.AIRun.properties.human_correction.nullable).toBe(true)
  })
})
