<template>
  <div class="space-y-4">
    <h1 class="text-2xl font-semibold">syifa — PhD study companion</h1>
    <p v-if="auth.isLoggedIn">Welcome, {{ auth.user?.email }}.</p>
    <p v-else>
      <NuxtLink to="/login" class="underline">Log in</NuxtLink> or
      <NuxtLink to="/signup" class="underline">sign up</NuxtLink> to get started.
    </p>
  </div>
</template>

<script setup lang="ts">
import { useAuthStore } from "~/stores/auth"
const auth = useAuthStore()
</script>
