import { QueryClient } from "@tanstack/react-query";

/** Shared client; cleared whenever the signed-in user changes (see setToken in api.ts). */
export const queryClient = new QueryClient({
  defaultOptions: { queries: { refetchOnWindowFocus: false, retry: 1 } },
});
