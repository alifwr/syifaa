import { useAuthStore } from "~/stores/auth"

export function useStream() {
  const config = useRuntimeConfig()
  const auth = useAuthStore()

  async function* postSSE(path: string, body: unknown): AsyncGenerator<string> {
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
    }
    if (auth.access) headers.Authorization = `Bearer ${auth.access}`

    const resp = await fetch(`${config.public.apiBase}${path}`, {
      method: "POST", headers, body: JSON.stringify(body),
    })
    if (!resp.ok || !resp.body) {
      const text = await resp.text()
      throw new Error(`${resp.status}: ${text}`)
    }
    const reader = resp.body.getReader()
    const decoder = new TextDecoder("utf-8")
    let buf = ""
    while (true) {
      const { value, done } = await reader.read()
      if (done) break
      buf += decoder.decode(value, { stream: true })
      const frames = buf.split("\n\n")
      buf = frames.pop() || ""
      for (const f of frames) {
        const lines = f.split("\n").filter(l => l.startsWith("data: "))
        if (!lines.length) continue
        const payload = lines.map(l => l.slice(6)).join("\n")
        if (payload === "[DONE]") return
        yield payload
      }
    }
  }

  return { postSSE }
}
