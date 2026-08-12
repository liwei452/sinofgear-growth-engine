import { render } from "@testing-library/vue"
import { defineComponent, nextTick, ref } from "vue"
import { afterEach, expect, it, vi } from "vitest"

import OperationModal from "./OperationModal.vue"
import { useModalFocus } from "../composables/useModalFocus"

afterEach(() => {
  document.body.querySelectorAll("[data-modal-test-root]").forEach((element) => element.remove())
  vi.restoreAllMocks()
})

it("does not apply delayed inert, aria-hidden, focus, or key handlers after immediate unmount", async () => {
  const existing = document.createElement("div")
  existing.dataset.modalTestRoot = "existing"
  existing.setAttribute("aria-hidden", "menu")
  document.body.append(existing)
  const addListener = vi.spyOn(document, "addEventListener")
  const close = vi.fn()
  const result = render(OperationModal, {
    props: { title: "测试弹窗", titleId: "test-modal-title", onClose: close },
  })

  result.unmount()
  await nextTick()
  await Promise.resolve()
  document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }))
  document.dispatchEvent(new KeyboardEvent("keydown", { key: "Tab", bubbles: true }))

  expect(existing).not.toHaveAttribute("inert")
  expect(existing).toHaveAttribute("aria-hidden", "menu")
  expect(addListener.mock.calls.filter(([type]) => type === "keydown")).toHaveLength(0)
  expect(close).not.toHaveBeenCalled()
  expect(document.querySelector("[role='dialog']")).toBeNull()
})

it("cancels modal setup when persistent element refs outlive an immediate component unmount", async () => {
  const background = document.createElement("div")
  background.dataset.modalTestRoot = "background"
  document.body.append(background)
  const backdrop = document.createElement("div")
  backdrop.dataset.modalTestRoot = "backdrop"
  const dialog = document.createElement("section")
  const heading = document.createElement("h2")
  backdrop.append(dialog)
  dialog.append(heading)
  document.body.append(backdrop)
  const addListener = vi.spyOn(document, "addEventListener")
  const close = vi.fn()
  const Harness = defineComponent({
    setup() {
      useModalFocus({ backdrop: ref(backdrop), dialog: ref(dialog), initialFocus: ref(heading), close })
      return () => null
    },
  })
  const result = render(Harness)

  result.unmount()
  await nextTick()
  await Promise.resolve()
  document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }))

  expect(background).not.toHaveAttribute("inert")
  expect(background).not.toHaveAttribute("aria-hidden")
  expect(addListener.mock.calls.filter(([type]) => type === "keydown")).toHaveLength(0)
  expect(close).not.toHaveBeenCalled()
})
