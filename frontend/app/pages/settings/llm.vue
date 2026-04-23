<template>
  <div class="max-w-2xl mx-auto space-y-6">
    <h1 class="text-xl font-semibold">LLM configuration</h1>

    <section class="space-y-2">
      <h2 class="font-medium">Your configs</h2>
      <ul v-if="configs.length" class="space-y-2">
        <li v-for="c in configs" :key="c.id"
            class="flex items-center justify-between border border-neutral-200 dark:border-neutral-800 rounded px-3 py-2">
          <div>
            <div class="font-mono text-sm">{{ c.name }} <span v-if="c.is_active" class="text-green-600">(active)</span></div>
            <div class="text-xs text-neutral-500">chat: {{ c.chat_model }} · embed: {{ c.embed_model }} (dim {{ c.embed_dim }})</div>
          </div>
          <div class="flex gap-2">
            <button @click="activate(c.id)" :disabled="c.is_active"
                    class="text-sm underline disabled:opacity-40">Activate</button>
            <button @click="testConn(c.id)" class="text-sm underline">Test</button>
            <button @click="remove(c.id)" class="text-sm underline text-red-600">Delete</button>
          </div>
        </li>
      </ul>
      <p v-else class="text-sm text-neutral-500">No configs yet.</p>
      <p v-if="testResult" class="text-sm font-mono">{{ testResult }}</p>
    </section>

    <section class="space-y-3">
      <h2 class="font-medium">Add new config</h2>
      <form @submit.prevent="create" class="grid grid-cols-1 md:grid-cols-2 gap-3">
        <input v-model="form.name" placeholder="name (e.g. openrouter)" required class="input" />
        <div />
        <input v-model="form.chat_base_url" placeholder="chat base_url (https://...)" required class="input" />
        <input v-model="form.chat_model" placeholder="chat model" required class="input" />
        <input v-model="form.chat_api_key" placeholder="chat API key" type="password" required class="input" />
        <div />
        <input v-model="form.embed_base_url" placeholder="embed base_url" required class="input" />
        <input v-model="form.embed_model" placeholder="embed model" required class="input" />
        <input v-model="form.embed_api_key" placeholder="embed API key" type="password" required class="input" />
        <input v-model.number="form.embed_dim" type="number" min="1" max="8192" placeholder="embed dim" required class="input" />
        <button class="col-span-full rounded bg-neutral-900 text-white dark:bg-white dark:text-neutral-900 px-3 py-2">
          Save
        </button>
      </form>
      <p v-if="error" class="text-red-600 text-sm">{{ error }}</p>
    </section>
  </div>
</template>

<style scoped>
@reference "tailwindcss";
.input { @apply rounded border border-neutral-300 dark:border-neutral-700 bg-transparent px-3 py-2; }
</style>

<script setup lang="ts">
type Cfg = {
  id: string; name: string; chat_model: string; embed_model: string;
  embed_dim: number; is_active: boolean;
  chat_base_url: string; embed_base_url: string;
}
const { call } = useApi()
const configs = ref<Cfg[]>([])
const error = ref("")
const testResult = ref("")

const form = reactive({
  name: "", chat_base_url: "", chat_api_key: "", chat_model: "",
  embed_base_url: "", embed_api_key: "", embed_model: "", embed_dim: 1536,
})

async function refresh() { configs.value = await call<Cfg[]>("/llm-config") }
onMounted(refresh)

async function create() {
  error.value = ""
  try {
    await call("/llm-config", { method: "POST", body: JSON.stringify(form) })
    Object.assign(form, {
      name: "", chat_base_url: "", chat_api_key: "", chat_model: "",
      embed_base_url: "", embed_api_key: "", embed_model: "", embed_dim: 1536,
    })
    await refresh()
  } catch (e: any) { error.value = e.message }
}

async function activate(id: string) {
  await call(`/llm-config/${id}/activate`, { method: "POST" })
  await refresh()
}
async function remove(id: string) {
  await call(`/llm-config/${id}`, { method: "DELETE" })
  await refresh()
}
async function testConn(id: string) {
  testResult.value = "testing…"
  const r = await call<{ chat: string; embed: string }>(`/llm-config/${id}/test`, { method: "POST" })
  testResult.value = `chat: ${r.chat} · embed: ${r.embed}`
}
</script>
