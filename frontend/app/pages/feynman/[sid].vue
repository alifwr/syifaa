<template>
  <div v-if="session" class="max-w-2xl mx-auto space-y-4">
    <NuxtLink to="/papers" class="text-sm underline">← back to papers</NuxtLink>
    <h1 class="text-xl font-semibold">Feynman session</h1>
    <div class="text-xs text-neutral-500">
      target: {{ session.target_concept_id.slice(0, 8) }} ·
      kind: {{ session.kind }} ·
      score: {{ session.quality_score ?? "—" }}
    </div>

    <div class="space-y-2 border border-neutral-200 dark:border-neutral-800 rounded p-3 max-h-[60vh] overflow-y-auto">
      <div v-for="(t, i) in displayTurns" :key="i"
           class="text-sm"
           :class="t.role === 'user' ? 'text-neutral-900 dark:text-neutral-100' : 'text-neutral-600 dark:text-neutral-400'">
        <span class="font-mono text-xs uppercase tracking-wide">{{ t.role }}</span>
        <p class="whitespace-pre-wrap">{{ t.content }}</p>
      </div>
      <div v-if="streaming" class="text-sm text-neutral-600 dark:text-neutral-400">
        <span class="font-mono text-xs uppercase tracking-wide">assistant</span>
        <p class="whitespace-pre-wrap">{{ assistantBuffer }}<span class="animate-pulse">▌</span></p>
      </div>
    </div>

    <form @submit.prevent="onSend" class="flex gap-2" v-if="!session.ended_at">
      <input v-model="draft" placeholder="explain it back…"
             :disabled="streaming"
             class="flex-1 input" />
      <button class="rounded bg-neutral-900 text-white dark:bg-white dark:text-neutral-900 px-3 py-2"
              :disabled="streaming || !draft.trim()">
        Send
      </button>
      <button type="button" @click="onEnd"
              class="rounded border border-red-500 text-red-600 px-3 py-2 text-sm"
              :disabled="streaming">
        End
      </button>
    </form>
    <p v-else class="text-sm text-neutral-500">
      Session ended. quality score: <span class="font-mono">{{ session.quality_score }}</span>
    </p>
    <p v-if="error" class="text-red-600 text-sm">{{ error }}</p>
  </div>
  <p v-else-if="loading" class="text-sm text-neutral-500">Loading…</p>
  <p v-else class="text-sm text-red-600">Session not found.</p>
</template>

<style scoped>
@reference "tailwindcss";
.input { @apply rounded border border-neutral-300 dark:border-neutral-700 bg-transparent px-3 py-2; }
</style>

<script setup lang="ts">
type Turn = { role: string; content: string; ts: string }
type Session = {
  id: string; user_id: string; paper_id: string | null;
  target_concept_id: string; kind: string;
  started_at: string; ended_at: string | null;
  quality_score: number | null;
  transcript: Turn[]
}
const route = useRoute()
const { call } = useApi()
const { postSSE } = useStream()

const session = ref<Session | null>(null)
const loading = ref(true)
const draft = ref("")
const assistantBuffer = ref("")
const streaming = ref(false)
const error = ref("")

const displayTurns = computed(() =>
  (session.value?.transcript ?? []).filter(t => t.role !== "system")
)

async function load() {
  try { session.value = await call<Session>(`/feynman/${route.params.sid}`) }
  catch { session.value = null }
  finally { loading.value = false }
}
onMounted(load)

async function onSend() {
  if (!draft.value.trim() || !session.value) return
  error.value = ""
  streaming.value = true
  assistantBuffer.value = ""
  const content = draft.value
  draft.value = ""
  session.value.transcript.push({
    role: "user", content, ts: new Date().toISOString(),
  })
  try {
    for await (const chunk of postSSE(`/feynman/${route.params.sid}/message`, { content })) {
      try {
        const parsed = JSON.parse(chunk)
        if (parsed && typeof parsed === "object" && "error" in parsed) {
          error.value = parsed.error as string
          continue
        }
      } catch {/* plain text — fine */}
      assistantBuffer.value += chunk
    }
    session.value.transcript.push({
      role: "assistant", content: assistantBuffer.value, ts: new Date().toISOString(),
    })
  } catch (e: any) {
    error.value = e?.message || "stream failed"
  } finally {
    assistantBuffer.value = ""
    streaming.value = false
  }
}

async function onEnd() {
  try {
    const r = await call<{ quality_score: number }>(`/feynman/${route.params.sid}/end`, { method: "POST" })
    if (session.value) {
      session.value.quality_score = r.quality_score
      session.value.ended_at = new Date().toISOString()
    }
  } catch (e: any) {
    error.value = e?.message || "end failed"
  }
}
</script>
