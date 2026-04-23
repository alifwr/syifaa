<template>
  <div class="max-w-sm mx-auto space-y-4">
    <h1 class="text-xl font-semibold">Create account</h1>
    <form @submit.prevent="submit" class="space-y-3">
      <input v-model="email" type="email" placeholder="email" required
             class="w-full rounded border border-neutral-300 dark:border-neutral-700 bg-transparent px-3 py-2" />
      <input v-model="password" type="password" placeholder="password (min 12 chars)" minlength="12" required
             class="w-full rounded border border-neutral-300 dark:border-neutral-700 bg-transparent px-3 py-2" />
      <button class="w-full rounded bg-neutral-900 text-white dark:bg-white dark:text-neutral-900 px-3 py-2">
        Sign up
      </button>
    </form>
    <p v-if="error" class="text-red-600 text-sm">{{ error }}</p>
    <p class="text-sm">
      Or <button class="underline" @click="google">continue with Google</button>.
    </p>
    <p class="text-sm">Already have an account? <NuxtLink to="/login" class="underline">Log in</NuxtLink>.</p>
  </div>
</template>

<script setup lang="ts">
import { useAuthStore } from "~/stores/auth"
const auth = useAuthStore()
const { call } = useApi()
const email = ref("")
const password = ref("")
const error = ref("")

async function submit() {
  error.value = ""
  try {
    await call("/auth/signup", {
      method: "POST",
      body: JSON.stringify({ email: email.value, password: password.value }),
    })
    const pair = await call<{ access_token: string; refresh_token: string; token_type: string }>(
      "/auth/login",
      {
        method: "POST",
        body: JSON.stringify({ email: email.value, password: password.value }),
      },
    )
    auth.set(pair)
    await auth.fetchMe()
    await navigateTo("/")
  } catch (e: any) {
    error.value = e.message
  }
}

async function google() {
  const cfg = useRuntimeConfig()
  const r = await fetch(`${cfg.public.apiBase}/auth/google/login`)
  const { authorization_url } = await r.json()
  window.location.href = authorization_url
}
</script>
