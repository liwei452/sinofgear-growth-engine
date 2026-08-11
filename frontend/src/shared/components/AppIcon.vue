<script setup lang="ts">
export type AppIconName =
  | "home"
  | "megaphone"
  | "users"
  | "chart"
  | "company"
  | "settings"
  | "bell"
  | "globe"
  | "chevron"
  | "check"
  | "search"
  | "document"
  | "sparkles"
  | "star"

defineProps<{ name: AppIconName }>()
</script>

<template>
  <svg
    :data-testid="`app-icon-${name}`"
    class="app-icon"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="1.8"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
    focusable="false"
  >
    <template v-if="name === 'home'">
      <path d="m3 10 9-7 9 7v10a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z" />
    </template>
    <template v-else-if="name === 'megaphone'">
      <path d="M4 14h3l9 4V6l-9 4H4z" />
      <path d="m7 14 1.5 5H11l-1.5-5" />
      <path d="M19 9.5a3.5 3.5 0 0 1 0 5" />
    </template>
    <template v-else-if="name === 'users'">
      <circle cx="9" cy="8" r="3" />
      <path d="M3.5 20a5.5 5.5 0 0 1 11 0" />
      <path d="M16 5.5a2.5 2.5 0 0 1 0 5" />
      <path d="M16.5 14.5A4.5 4.5 0 0 1 21 19" />
    </template>
    <template v-else-if="name === 'chart'">
      <path d="M4 20V10" />
      <path d="M10 20V4" />
      <path d="M16 20v-7" />
      <path d="M22 20H2" />
    </template>
    <template v-else-if="name === 'company'">
      <path d="M4 21V5a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v16" />
      <path d="M16 10h3a1 1 0 0 1 1 1v10" />
      <path d="M8 8h4M8 12h4M8 16h4M10 21v-2" />
    </template>
    <template v-else-if="name === 'settings'">
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.7 1.7 0 0 0 .34 1.88l.06.06-2.1 2.1-.06-.06a1.7 1.7 0 0 0-1.88-.34 1.7 1.7 0 0 0-1.03 1.55v.08h-3v-.08A1.7 1.7 0 0 0 10.7 18.6a1.7 1.7 0 0 0-1.88.34l-.06.06-2.1-2.1.06-.06A1.7 1.7 0 0 0 7.06 15a1.7 1.7 0 0 0-1.55-1.03h-.08v-3h.08A1.7 1.7 0 0 0 7.06 9.94a1.7 1.7 0 0 0-.34-1.88l-.06-.06 2.1-2.1.06.06a1.7 1.7 0 0 0 1.88.34 1.7 1.7 0 0 0 1.03-1.55v-.08h3v.08a1.7 1.7 0 0 0 1.03 1.55 1.7 1.7 0 0 0 1.88-.34l.06-.06 2.1 2.1-.06.06a1.7 1.7 0 0 0-.34 1.88 1.7 1.7 0 0 0 1.55 1.03h.08v3h-.08A1.7 1.7 0 0 0 19.4 15Z" />
    </template>
    <template v-else-if="name === 'bell'">
      <path d="M18 10a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9" />
      <path d="M10 22h4" />
    </template>
    <template v-else-if="name === 'globe'">
      <circle cx="12" cy="12" r="9" />
      <path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18" />
    </template>
    <template v-else-if="name === 'chevron'">
      <path d="m8 10 4 4 4-4" />
    </template>
    <template v-else-if="name === 'check'">
      <path d="m5 12 4 4L19 6" />
    </template>
    <template v-else-if="name === 'search'">
      <circle cx="10.5" cy="10.5" r="5.5" />
      <path d="m15 15 4.5 4.5" />
    </template>
    <template v-else-if="name === 'document'">
      <path d="M6 3h8l4 4v14H6z" />
      <path d="M14 3v5h5M9 13h6M9 17h6" />
    </template>
    <template v-else-if="name === 'sparkles'">
      <path d="m12 3 .9 4.1L17 8l-4.1.9L12 13l-.9-4.1L7 8l4.1-.9z" />
      <path d="m19 14 .5 2.5L22 17l-2.5.5L19 20l-.5-2.5L16 17l2.5-.5z" />
      <path d="m5 15 .6 2.4L8 18l-2.4.6L5 21l-.6-2.4L2 18l2.4-.6z" />
    </template>
    <template v-else>
      <path d="m12 3 2.8 5.7 6.2.9-4.5 4.4 1.1 6.2-5.6-3-5.6 3 1.1-6.2L3 9.6l6.2-.9z" />
    </template>
  </svg>
</template>
