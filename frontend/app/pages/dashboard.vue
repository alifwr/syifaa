<template>
  <div class="max-w-3xl mx-auto space-y-6">
    <h1 class="text-xl font-semibold">Dashboard</h1>

    <div class="border border-neutral-200 dark:border-neutral-800 rounded p-4">
      <div class="text-xs uppercase tracking-wide text-neutral-500">Concepts</div>
      <div class="text-3xl font-mono">{{ data?.concept_count ?? "—" }}</div>
    </div>

    <section class="space-y-2">
      <h2 class="font-medium">Recent Feynman sessions</h2>
      <table v-if="data && data.sessions.length" class="w-full text-sm">
        <thead class="text-left text-xs uppercase tracking-wide text-neutral-500">
          <tr><th class="py-1">When</th><th class="py-1">Score</th></tr>
        </thead>
        <tbody>
          <tr v-for="(s, i) in data.sessions" :key="i" class="border-t border-neutral-200 dark:border-neutral-800">
            <td class="py-1">{{ new Date(s.started_at).toLocaleString() }}</td>
            <td class="py-1 font-mono">{{ s.quality_score.toFixed(2) }}</td>
          </tr>
        </tbody>
      </table>
      <p v-else class="text-sm text-neutral-500">No completed sessions yet.</p>
    </section>
  </div>
</template>

<script setup lang="ts">
type DashboardData = {
  concept_count: number
  sessions: { started_at: string; quality_score: number }[]
}
const { call } = useApi()
const data = ref<DashboardData | null>(null)
async function load() { data.value = await call<DashboardData>("/dashboard") }
onMounted(load)
</script>
