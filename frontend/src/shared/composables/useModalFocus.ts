import { nextTick, onBeforeUnmount, onMounted, type Ref } from "vue"

type InertState = { count: number; hadAttribute: boolean; value: string | null }

const inertStates = new Map<HTMLElement, InertState>()
const modalStack: symbol[] = []

const focusableSelector = [
  "button:not([disabled])",
  "[href]",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  "[tabindex]:not([tabindex='-1'])",
].join(",")

function setInert(element: HTMLElement): void {
  const current = inertStates.get(element)
  if (current) {
    current.count += 1
    return
  }
  inertStates.set(element, {
    count: 1,
    hadAttribute: element.hasAttribute("inert"),
    value: element.getAttribute("inert"),
  })
  element.setAttribute("inert", "")
}

function releaseInert(element: HTMLElement): void {
  const current = inertStates.get(element)
  if (!current) return
  current.count -= 1
  if (current.count > 0) return
  inertStates.delete(element)
  if (current.hadAttribute) element.setAttribute("inert", current.value ?? "")
  else element.removeAttribute("inert")
}

function focusableElements(dialog: HTMLElement): HTMLElement[] {
  return [...dialog.querySelectorAll<HTMLElement>(focusableSelector)]
    .filter((element) => !(element as HTMLButtonElement).disabled
      && element.getAttribute("aria-hidden") !== "true"
      && !element.closest("[inert]"))
}

export function useModalFocus(options: {
  backdrop: Ref<HTMLElement | null>
  dialog: Ref<HTMLElement | null>
  initialFocus: Ref<HTMLElement | null>
  close: () => void
}): void {
  const token = Symbol("modal")
  const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null
  const inerted: HTMLElement[] = []

  function onKeydown(event: KeyboardEvent): void {
    if (modalStack.at(-1) !== token) return
    const dialog = options.dialog.value
    if (!dialog) return
    if (event.key === "Escape") {
      event.preventDefault()
      event.stopPropagation()
      options.close()
      return
    }
    if (event.key !== "Tab") return
    const focusable = focusableElements(dialog)
    if (!focusable.length) {
      event.preventDefault()
      options.initialFocus.value?.focus()
      return
    }
    const first = focusable[0]
    const last = focusable[focusable.length - 1]
    const active = document.activeElement
    if (event.shiftKey && (active === first || !dialog.contains(active))) {
      event.preventDefault()
      last?.focus()
    } else if (!event.shiftKey && (active === last || !dialog.contains(active))) {
      event.preventDefault()
      first?.focus()
    }
  }

  onMounted(async () => {
    await nextTick()
    const backdrop = options.backdrop.value
    if (!backdrop) return
    for (const child of [...document.body.children]) {
      if (!(child instanceof HTMLElement) || child === backdrop || child.contains(backdrop)) continue
      setInert(child)
      inerted.push(child)
    }
    modalStack.push(token)
    document.addEventListener("keydown", onKeydown)
    options.initialFocus.value?.focus()
  })

  onBeforeUnmount(() => {
    document.removeEventListener("keydown", onKeydown)
    const index = modalStack.lastIndexOf(token)
    if (index >= 0) modalStack.splice(index, 1)
    for (const element of inerted) releaseInert(element)
    if (opener?.isConnected) opener.focus()
  })
}
