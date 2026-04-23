import { defineStore } from "pinia"

type User = { id: string; email: string }
type TokenPair = { access_token: string; refresh_token: string; token_type: string }

export const useAuthStore = defineStore("auth", {
  state: () => ({
    access: (import.meta.client ? localStorage.getItem("access") : null) as string | null,
    refresh: (import.meta.client ? localStorage.getItem("refresh") : null) as string | null,
    user: null as User | null,
  }),
  getters: {
    isLoggedIn: (s) => !!s.access,
  },
  actions: {
    _persist() {
      if (!import.meta.client) return
      if (this.access) localStorage.setItem("access", this.access)
      else localStorage.removeItem("access")
      if (this.refresh) localStorage.setItem("refresh", this.refresh)
      else localStorage.removeItem("refresh")
    },
    set(pair: TokenPair) {
      this.access = pair.access_token
      this.refresh = pair.refresh_token
      this._persist()
    },
    clear() {
      this.access = null
      this.refresh = null
      this.user = null
      this._persist()
    },
    async fetchMe() {
      const cfg = useRuntimeConfig()
      if (!this.access) return
      const r = await fetch(`${cfg.public.apiBase}/auth/me`, {
        headers: { Authorization: `Bearer ${this.access}` },
      })
      if (r.ok) this.user = (await r.json()) as User
      else this.clear()
    },
    async tryRefresh(): Promise<boolean> {
      if (!this.refresh) return false
      const cfg = useRuntimeConfig()
      const r = await fetch(`${cfg.public.apiBase}/auth/refresh`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: this.refresh }),
      })
      if (!r.ok) { this.clear(); return false }
      this.set(await r.json())
      return true
    },
    async logout() {
      this.clear()
      await navigateTo("/login")
    },
  },
})
