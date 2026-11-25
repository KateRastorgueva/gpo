import { createFileRoute } from "@tanstack/react-router"

import { SupportPage } from "@/components/Support/SupportPage"

export const Route = createFileRoute("/_layout/support")({
  component: () => <SupportPage />,
  head: () => ({
    meta: [{ title: "Техподдержка ТУСУР" }],
  }),
})
