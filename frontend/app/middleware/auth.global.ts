import { useAuthStore } from "~/stores/auth"

const PROTECTED = [/^\/settings/, /^\/papers/, /^\/review/, /^\/dashboard/]

export default defineNuxtRouteMiddleware(async (to) => {
  const auth = useAuthStore()
  if (auth.access && !auth.user) await auth.fetchMe()
  if (PROTECTED.some((p) => p.test(to.path)) && !auth.isLoggedIn) {
    return navigateTo("/login")
  }
})
