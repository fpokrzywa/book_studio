import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, call, setCsrfToken, type Schemas } from "./client";

export type AuthState = Schemas["AuthStateOut"];

export const authKey = ["auth", "state"] as const;

/** Who is signed in. Keeps the client's CSRF token in step with the session. */
export function useAuthState() {
  return useQuery<AuthState>({
    queryKey: authKey,
    queryFn: async () => {
      const state = await call(api.GET("/api/auth/state"));
      setCsrfToken(state.csrf_token ?? null);
      return state;
    },
    staleTime: 60_000,
    retry: 1,
  });
}

function useAfterAuth() {
  const qc = useQueryClient();
  return (state: AuthState) => {
    setCsrfToken(state.csrf_token ?? null);
    // A different session may see different data: drop everything cached for the previous one.
    qc.removeQueries({ predicate: (q) => q.queryKey[0] !== "auth" });
    qc.setQueryData(authKey, state);
  };
}

export function useSignIn() {
  const after = useAfterAuth();
  return useMutation({
    mutationFn: (body: { username: string; password: string }) => call(api.POST("/api/auth/login", { body })),
    onSuccess: after,
  });
}

export function useSetup() {
  const after = useAfterAuth();
  return useMutation({
    mutationFn: (body: { username: string; password: string; setup_code: string }) =>
      call(api.POST("/api/auth/setup", { body })),
    onSuccess: after,
  });
}

export function useSignOut() {
  const after = useAfterAuth();
  return useMutation({
    mutationFn: () => call(api.POST("/api/auth/logout")),
    onSuccess: after,
  });
}

export function useChangePassword() {
  return useMutation({
    mutationFn: (body: { current_password: string; new_password: string }) =>
      call(api.POST("/api/auth/password", { body })),
  });
}

export function useSignOutOthers() {
  return useMutation({ mutationFn: () => call(api.POST("/api/auth/sign-out-others")) });
}
