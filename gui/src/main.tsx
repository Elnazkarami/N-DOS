import { RouterProvider, createRouter } from "@tanstack/react-router";
import { QueryClient } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { routeTree } from "./routeTree.gen";
import "./styles.css";

// Served from a local Python process, so there is no server rendering and no
// data loading to hydrate: the interface asks the server for what it needs.
//
// The root route declares a query client in its context and is what puts the
// provider around the tree, so it has to be handed one here. Without it the
// provider was being given undefined, and the first component to ask for a
// query client would have thrown.
const queryClient = new QueryClient();
const router = createRouter({
  routeTree,
  defaultPreload: "intent",
  context: { queryClient },
});

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}

const container = document.getElementById("root");
if (!container) throw new Error("no #root element in index.html");

createRoot(container).render(
  <StrictMode>
    <RouterProvider router={router} />
  </StrictMode>,
);
