import { RouterProvider, createRouter } from "@tanstack/react-router";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { routeTree } from "./routeTree.gen";
import "./styles.css";

// Served from a local Python process, so there is no server rendering and no
// data loading to hydrate: the interface asks the server for what it needs.
const router = createRouter({ routeTree, defaultPreload: "intent" });
const queryClient = new QueryClient();

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}

const container = document.getElementById("root");
if (!container) throw new Error("no #root element in index.html");

createRoot(container).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>,
);
