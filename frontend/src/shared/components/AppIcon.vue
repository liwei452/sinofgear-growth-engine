<script setup lang="ts">
import { computed } from "vue"

export type IconName =
  | "calendar-days"
  | "users-round"
  | "map-pinned"
  | "sparkles"
  | "clipboard-check"
  | "calendar-clock"
  | "share-2"
  | "chart-column"
  | "package-search"
  | "book-open"
  | "images"
  | "building-2"
  | "settings"
  | "circle-check"
  | "panel-left"
  | "chevron-down"
  | "log-out"
  | "inbox"

const props = withDefaults(defineProps<{
  name: IconName
  size?: number
  strokeWidth?: number
}>(), {
  size: 20,
  strokeWidth: 1.8,
})

const iconPaths: Record<IconName, string[]> = {
  "calendar-days": ["M8 2v4M16 2v4M3 9h18", "M5 4h14a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2Z", "M8 13h.01M12 13h.01M16 13h.01M8 17h.01M12 17h.01"],
  "users-round": ["M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2", "M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8Z", "M22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"],
  "map-pinned": ["m3 6 6-3 6 3 6-3v15l-6 3-6-3-6 3Z", "M9 3v15M15 6v15", "M18 8.5a2.5 2.5 0 1 0-5 0c0 1.9 2.5 4.5 2.5 4.5S18 10.4 18 8.5Z"],
  "sparkles": ["m12 3-1.1 3.1a2 2 0 0 1-1.2 1.2L6.5 8.5l3.2 1.1a2 2 0 0 1 1.2 1.2L12 14l1.1-3.2a2 2 0 0 1 1.2-1.2l3.2-1.1-3.2-1.2a2 2 0 0 1-1.2-1.2Z", "m5 16-.6 1.6a1 1 0 0 1-.6.6L2 19l1.8.7a1 1 0 0 1 .6.6L5 22l.6-1.7a1 1 0 0 1 .6-.6L8 19l-1.8-.8a1 1 0 0 1-.6-.6ZM19 15l-.7 1.8a1 1 0 0 1-.6.6L16 18l1.7.7a1 1 0 0 1 .6.6L19 21l.7-1.7a1 1 0 0 1 .6-.6L22 18l-1.7-.6a1 1 0 0 1-.6-.6Z"],
  "clipboard-check": ["M9 5h6M9 3h6v4H9Z", "M7 5H5a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2h-2", "m8 14 2.5 2.5L16 11"],
  "calendar-clock": ["M16 2v4M8 2v4M3 9h18", "M14 22H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v7", "M18 16v3l2 1M18 22a4 4 0 1 0 0-8 4 4 0 0 0 0 8Z"],
  "share-2": ["M18 8a3 3 0 1 0 0-6 3 3 0 0 0 0 6ZM6 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6ZM18 24a3 3 0 1 0 0-6 3 3 0 0 0 0 6Z", "m8.6 13.5 6.8-4M8.6 16.5l6.8 4"],
  "chart-column": ["M4 20V10h4v10M10 20V4h4v16M16 20v-7h4v7M2 20h20"],
  "package-search": ["m3 7 9 5 9-5-9-5Z", "M3 7v10l9 5 5-2.8M21 7v6", "M12 12v10M16 16a3 3 0 1 0 6 0 3 3 0 0 0-6 0Zm5.8 2.2L21 21.4"],
  "book-open": ["M2 4.5A2.5 2.5 0 0 1 4.5 2H11v18H4.5A2.5 2.5 0 0 0 2 22.5ZM22 4.5A2.5 2.5 0 0 0 19.5 2H13v18h6.5a2.5 2.5 0 0 1 2.5 2.5Z"],
  "images": ["M3 5a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z", "m3 15 4-4 4 4 3-3 5 5", "M15 8h.01", "M19 7h1a2 2 0 0 1 2 2v11a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2v-1"],
  "building-2": ["M6 22V4a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v18M2 22h20", "M10 6h4M10 10h4M10 14h4M10 18h4"],
  "settings": ["M12 15.5a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7Z", "M19.4 15a1.7 1.7 0 0 0 .34 1.88l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06A1.7 1.7 0 0 0 15 19.4a1.7 1.7 0 0 0-1 .6 1.7 1.7 0 0 0-.4 1.1V21a2 2 0 0 1-4 0v-.09A1.7 1.7 0 0 0 8.6 19.4a1.7 1.7 0 0 0-1.88.34l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.7 1.7 0 0 0 4.6 15a1.7 1.7 0 0 0-.6-1 1.7 1.7 0 0 0-1.1-.4H3a2 2 0 0 1 0-4h.09A1.7 1.7 0 0 0 4.6 8.6a1.7 1.7 0 0 0-.34-1.88l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.7 1.7 0 0 0 9 4.6a1.7 1.7 0 0 0 1-.6 1.7 1.7 0 0 0 .4-1.1V3a2 2 0 0 1 4 0v.09A1.7 1.7 0 0 0 15.4 4.6a1.7 1.7 0 0 0 1.88-.34l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.7 1.7 0 0 0 19.4 9c.08.38.29.73.6 1 .3.25.7.4 1.1.4h.09a2 2 0 0 1 0 4h-.09c-.4 0-.8.14-1.1.4-.31.27-.52.62-.6 1Z"],
  "circle-check": ["M22 11.1V12a10 10 0 1 1-5.9-9.1", "m9 11 3 3L22 4"],
  "panel-left": ["M3 3h18v18H3Z", "M9 3v18", "m15 9-3 3 3 3"],
  "chevron-down": ["m6 9 6 6 6-6"],
  "log-out": ["M10 17l5-5-5-5M15 12H3", "M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4"],
  "inbox": ["M4 4h16a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2Z", "M2 14h5l2 3h6l2-3h5"],
}

const paths = computed(() => iconPaths[props.name])
</script>

<template>
  <svg
    :width="size"
    :height="size"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    :stroke-width="strokeWidth"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
    focusable="false"
    :data-icon="name"
    :data-testid="`icon-${name}`"
  >
    <path v-for="path in paths" :key="path" :d="path" />
  </svg>
</template>
