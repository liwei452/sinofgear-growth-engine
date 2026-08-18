<script setup lang="ts">
import { useQuery } from "@tanstack/vue-query"
import { computed } from "vue"

import { currentUserQueryOptions } from "../auth/auth"
import ExecutiveAttributionPage from "../attribution/ExecutiveAttributionPage.vue"
import DashboardPage from "./DashboardPage.vue"

const currentUserQuery = useQuery(currentUserQueryOptions())
const isReadOnly = computed(
  () => currentUserQuery.data.value?.membership.role === "READ_ONLY",
)
</script>

<template>
  <ExecutiveAttributionPage v-if="isReadOnly" />
  <DashboardPage v-else />
</template>
