<template>
  <div class="max-w-sm mx-auto text-center py-16">
    <p v-if="!error">Signing you in…</p>
    <p v-else class="text-red-600 text-sm">{{ error }}</p>
  </div>
</template>

<script setup lang="ts">
import { useAuthStore } from "~/stores/auth"
const auth = useAuthStore()
const route = useRoute()
const cfg = useRuntimeConfig()
const error = ref("")

onMounted(async () => {
  const code = route.query.code as string | undefined
  const state = route.query.state as string | undefined
  if (!code) { error.value = "Missing code"; return }
  if (!state) { error.value = "Missing state"; return }
  try {
    const r = await fetch(`${cfg.public.apiBase}/auth/google/callback?code=${encodeURIComponent(code)}&state=${encodeURIComponent(state)}`)
    if (!r.ok) throw new Error(`${r.status}: ${await r.text()}`)
    const pair = await r.json()
    auth.set(pair)
    await auth.fetchMe()
    await navigateTo("/")
  } catch (e: any) {
    error.value = e.message
  }
})
</script>
