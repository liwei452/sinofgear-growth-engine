import { describe, expectTypeOf, it } from "vitest"
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
})
