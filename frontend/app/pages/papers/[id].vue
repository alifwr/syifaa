<template>
  <div v-if="paper" class="max-w-3xl mx-auto space-y-4">
    <NuxtLink to="/papers" class="text-sm underline">← back</NuxtLink>
    <h1 class="text-xl font-semibold">{{ paper.title }}</h1>
    <div class="text-xs text-neutral-500">
      uploaded {{ new Date(paper.uploaded_at).toLocaleString() }} · status: {{ paper.status }}
    </div>
    <div v-if="paper.parse_error" class="text-sm text-red-600 font-mono">{{ paper.parse_error }}</div>

    <div class="flex gap-2">
      <button v-if="paper.status !== 'uploaded'" @click="reingest"
              class="rounded border border-neutral-300 dark:border-neutral-700 px-3 py-2 text-sm">
        Reingest
      </button>
      <button @click="remove" class="rounded border border-red-500 text-red-600 px-3 py-2 text-sm">
        Delete
      </button>
    </div>
  </div>
  <p v-else-if="loading" class="text-sm text-neutral-500">Loading…</p>
  <p v-else class="text-sm text-red-600">Not found.</p>
</template>

<script setup lang="ts">
type Paper = {
  id: string; title: string; uploaded_at: string; status: string;
  parse_error: string | null;
}
const { call } = useApi()
const route = useRoute()
const router = useRouter()
const paper = ref<Paper | null>(null)
const loading = ref(true)

async function load() {
  try { paper.value = await call<Paper>(`/papers/${route.params.id}`) }
  catch { paper.value = null }
  finally { loading.value = false }
}
onMounted(load)

let poll: any = null
watch(paper, (p) => {
  if (p?.status === "uploaded" && !poll) poll = setInterval(load, 2000)
  if (p?.status !== "uploaded" && poll) { clearInterval(poll); poll = null }
})
onBeforeUnmount(() => poll && clearInterval(poll))

async function reingest() {
  await call(`/papers/${route.params.id}/reingest`, { method: "POST" })
  await load()
}
async function remove() {
  await call(`/papers/${route.params.id}`, { method: "DELETE" })
  await router.push("/papers")
}
</script>
