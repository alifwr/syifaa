<template>
  <div class="max-w-3xl mx-auto space-y-6">
    <h1 class="text-xl font-semibold">Review queue</h1>
    <p v-if="!items.length" class="text-sm text-neutral-500">Nothing due. Come back later.</p>
    <ul v-else class="space-y-2">
      <li v-for="it in items" :key="it.id"
          class="flex items-center justify-between border border-neutral-200 dark:border-neutral-800 rounded px-3 py-2">
        <div>
          <div class="font-medium">{{ it.concept_name }}</div>
          <div class="text-xs text-neutral-500">
            due {{ new Date(it.due_at).toLocaleString() }} ·
            interval {{ it.interval_days }}d ·
            ease {{ it.ease.toFixed(2) }} ·
            last score {{ it.last_score?.toFixed(2) ?? "—" }}
          </div>
        </div>
        <button @click="start(it.id)" :disabled="starting === it.id"
                class="rounded bg-neutral-900 text-white dark:bg-white dark:text-neutral-900 px-3 py-2 text-sm">
          {{ starting === it.id ? "starting…" : "Start review" }}
        </button>
      </li>
    </ul>
    <p v-if="error" class="text-red-600 text-sm">{{ error }}</p>
  </div>
</template>

<script setup lang="ts">
type Item = {
  id: string; concept_id: string; concept_name: string;
  embed_dim: number; ease: number; interval_days: number;
  due_at: string; last_score: number | null;
}
const { call } = useApi()
const router = useRouter()
const items = ref<Item[]>([])
const starting = ref("")
const error = ref("")

async function refresh() { items.value = await call<Item[]>("/review/due") }
onMounted(refresh)

async function start(id: string) {
  error.value = ""; starting.value = id
  try {
    const r = await call<{ id: string }>("/review/start", {
      method: "POST",
      body: JSON.stringify({ review_item_id: id }),
    })
    await router.push(`/feynman/${r.id}`)
  } catch (e: any) {
    error.value = e?.message || "start failed"
  } finally { starting.value = "" }
}
</script>
