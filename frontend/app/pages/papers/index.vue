<template>
  <div class="max-w-3xl mx-auto space-y-6">
    <h1 class="text-xl font-semibold">Papers</h1>

    <form @submit.prevent="onUpload" class="space-y-2 border border-neutral-200 dark:border-neutral-800 rounded p-3">
      <input v-model="title" placeholder="title" required class="input w-full" />
      <input ref="fileInput" type="file" accept="application/pdf" required />
      <button class="rounded bg-neutral-900 text-white dark:bg-white dark:text-neutral-900 px-3 py-2"
              :disabled="uploading">
        {{ uploading ? "Uploading…" : "Upload" }}
      </button>
      <p v-if="error" class="text-red-600 text-sm">{{ error }}</p>
    </form>

    <ul v-if="papers.length" class="space-y-2">
      <li v-for="p in papers" :key="p.id"
          class="flex items-center justify-between border border-neutral-200 dark:border-neutral-800 rounded px-3 py-2">
        <div>
          <NuxtLink :to="`/papers/${p.id}`" class="font-medium underline">{{ p.title }}</NuxtLink>
          <div class="text-xs text-neutral-500">
            {{ new Date(p.uploaded_at).toLocaleString() }} · status: {{ p.status }}
          </div>
          <div v-if="p.parse_error" class="text-xs text-red-600 font-mono">{{ p.parse_error }}</div>
        </div>
      </li>
    </ul>
    <p v-else class="text-sm text-neutral-500">No papers yet.</p>
  </div>
</template>

<style scoped>
@reference "tailwindcss";
.input { @apply rounded border border-neutral-300 dark:border-neutral-700 bg-transparent px-3 py-2; }
</style>

<script setup lang="ts">
type Paper = {
  id: string; title: string; uploaded_at: string; status: string;
  parse_error: string | null;
}
const { call, callUpload } = useApi()
const papers = ref<Paper[]>([])
const title = ref("")
const fileInput = ref<HTMLInputElement | null>(null)
const uploading = ref(false)
const error = ref("")

async function refresh() { papers.value = await call<Paper[]>("/papers") }
onMounted(refresh)

let poll: any = null
watch(papers, (ps) => {
  const pending = ps.some(p => p.status === "uploaded")
  if (pending && !poll) {
    poll = setInterval(refresh, 2000)
  } else if (!pending && poll) {
    clearInterval(poll); poll = null
  }
}, { immediate: true })
onBeforeUnmount(() => poll && clearInterval(poll))

async function onUpload() {
  error.value = ""
  const f = fileInput.value?.files?.[0]
  if (!f || !title.value) return
  uploading.value = true
  try {
    const fd = new FormData()
    fd.append("file", f)
    fd.append("title", title.value)
    await callUpload("/papers", fd)
    title.value = ""
    if (fileInput.value) fileInput.value.value = ""
    await refresh()
  } catch (e: any) {
    error.value = e?.message || "upload failed"
  } finally { uploading.value = false }
}
</script>
