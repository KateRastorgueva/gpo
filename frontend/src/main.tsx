import {
  MutationCache,
  QueryCache,
  QueryClient,
  QueryClientProvider,
} from "@tanstack/react-query"
import { createRouter, RouterProvider } from "@tanstack/react-router"
import { StrictMode } from "react"
import ReactDOM from "react-dom/client"
import { ApiError, OpenAPI } from "./client"
import { ThemeProvider } from "./components/theme-provider"
import { Toaster } from "./components/ui/sonner"
import "./index.css"
import { routeTree } from "./routeTree.gen"

const LOOPBACK_HOSTS = ["localhost", "127.0.0.1", "[::1]"]

// Адрес API. Пустой VITE_API_URL — тот же origin: /api проксирует сервер фронтенда
// (nginx или dev-сервер Vite). Loopback-адрес, вшитый при сборке, верен только на машине
// со стеком: при открытии через туннель или по IP браузер посетителя ушёл бы на свой
// localhost, поэтому в этом случае тоже берётся тот же origin.
const resolveApiBase = (): string => {
  const configured = (import.meta.env.VITE_API_URL ?? "")
    .trim()
    .replace(/\/+$/, "")
  if (!configured) return ""
  try {
    const { hostname } = new URL(configured)
    if (
      LOOPBACK_HOSTS.includes(hostname) &&
      !LOOPBACK_HOSTS.includes(window.location.hostname)
    ) {
      return ""
    }
  } catch {
    // Относительный адрес (например, "/backend") используем как есть
  }
  return configured
}

OpenAPI.BASE = resolveApiBase()
OpenAPI.TOKEN = async () => {
  return localStorage.getItem("access_token") || ""
}

// Страницы без входа: редирект на них из обработчика 401/403 вызвал бы
// перезагрузку и бесконечный цикл.
const PUBLIC_PATHS = [
  "/login",
  "/signup",
  "/reset-password",
  "/recover-password",
]

export const isPublicPath = (pathname: string): boolean =>
  PUBLIC_PATHS.some((p) => pathname === p || pathname.startsWith(`${p}/`))

const handleApiError = (error: Error) => {
  if (error instanceof ApiError && [401, 403].includes(error.status)) {
    localStorage.removeItem("access_token")
    if (!isPublicPath(window.location.pathname)) {
      window.location.href = "/login"
    }
  }
}
const queryClient = new QueryClient({
  queryCache: new QueryCache({
    onError: handleApiError,
  }),
  mutationCache: new MutationCache({
    onError: handleApiError,
  }),
})

const router = createRouter({ routeTree })
declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router
  }
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ThemeProvider defaultTheme="dark" storageKey="vite-ui-theme">
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
        <Toaster richColors closeButton />
      </QueryClientProvider>
    </ThemeProvider>
  </StrictMode>,
)
