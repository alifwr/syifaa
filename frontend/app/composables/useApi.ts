import { useAuthStore } from "~/stores/auth"

export const useApi = () => {
  const config = useRuntimeConfig()
  const auth = useAuthStore()

  const call = async <T>(path: string, init: RequestInit = {}): Promise<T> => {
    const headers = new Headers(init.headers || {})
    headers.set("Content-Type", "application/json")
    if (auth.access) headers.set("Authorization", `Bearer ${auth.access}`)

    const resp = await fetch(`${config.public.apiBase}${path}`, { ...init, headers })

    if (resp.status === 401 && auth.refresh) {
      const refreshed = await auth.tryRefresh()
      if (refreshed) {
        headers.set("Authorization", `Bearer ${auth.access}`)
        const retry = await fetch(`${config.public.apiBase}${path}`, { ...init, headers })
        return handle<T>(retry)
      }
      auth.clear()
    }
    return handle<T>(resp)
  }

  return { call }
}

async function handle<T>(resp: Response): Promise<T> {
  if (!resp.ok) {
    const body = await resp.text()
    throw new Error(`${resp.status}: ${body}`)
  }
  if (resp.status === 204) return undefined as T
  return (await resp.json()) as T
}
