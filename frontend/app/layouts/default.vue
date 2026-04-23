<template>
  <div class="min-h-screen flex flex-col">
    <header class="border-b border-neutral-200 dark:border-neutral-800 px-6 py-3 flex justify-between">
      <NuxtLink to="/" class="font-semibold">syifa</NuxtLink>
      <nav class="flex gap-4 text-sm">
        <NuxtLink to="/settings/llm">LLM</NuxtLink>
        <NuxtLink v-if="!auth.isLoggedIn" to="/login">Login</NuxtLink>
        <button v-else @click="auth.logout()" class="text-neutral-500 hover:underline">Logout</button>
      </nav>
    </header>
    <main class="flex-1 p-6"><slot /></main>
  </div>
</template>

<script setup lang="ts">
import { useAuthStore } from "~/stores/auth"
const auth = useAuthStore()
</script>
