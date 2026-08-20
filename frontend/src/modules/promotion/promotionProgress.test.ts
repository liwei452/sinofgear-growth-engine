import { expect, it } from "vitest"

import { promotionSteps } from "./promotionProgress"

it("makes company setup current and later work blocked when no persisted setup exists", () => {
  expect(promotionSteps({
    companyConfigured: false,
    marketConfigured: false,
    icpConfigured: false,
    discoveryStarted: false,
    contentPrepared: false,
    channelsConfigured: false,
    approvalReady: false,
  }).map(step => step.state)).toEqual([
    "current", "blocked", "blocked", "blocked", "blocked", "blocked", "blocked",
  ])
})

it("makes channels the single current step after prior persisted work is ready", () => {
  const steps = promotionSteps({
    companyConfigured: true,
    marketConfigured: true,
    icpConfigured: true,
    discoveryStarted: true,
    contentPrepared: true,
    channelsConfigured: false,
    approvalReady: false,
  })

  expect(steps.find(step => step.id === "channels")?.state).toBe("current")
  expect(steps.filter(step => step.state === "current")).toHaveLength(1)
})
