import "@fontsource-variable/literata/opsz.css";
import "@fontsource-variable/literata/opsz-italic.css";
import "@fontsource/atkinson-hyperlegible/400.css";
import "@fontsource/atkinson-hyperlegible/700.css";
import "./styles/tokens.css";
import "./styles/app.css";
import "./styles/manuscript.css";
import "./styles/ai.css";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { createBrowserRouter, RouterProvider } from "react-router";
import { routes } from "./app/routes";
import { AnnouncerProvider } from "./components/Announcer";
import { ApiError } from "./api/client";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // Retry only when Core may be briefly restarting; never retry 4xx.
      retry: (count, err) =>
        count < 2 && (!(err instanceof ApiError) || err.status === 0 || err.status >= 500),
      refetchOnWindowFocus: true,
    },
  },
});

const router = createBrowserRouter(routes);

const root = document.getElementById("root");
if (!root) throw new Error("missing #root");

createRoot(root).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <AnnouncerProvider>
        <RouterProvider router={router} />
      </AnnouncerProvider>
    </QueryClientProvider>
  </StrictMode>,
);
