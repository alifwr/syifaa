// Minimal placeholder; filled in by Task 13.
import { defineStore } from "pinia"

export const useAuthStore = defineStore("auth", {
  state: () => ({
    user: null as { id: string; email: string } | null,
  }),
  getters: {
    isLoggedIn: (s) => !!s.user,
  },
  actions: {
    async logout() {},
  },
})
