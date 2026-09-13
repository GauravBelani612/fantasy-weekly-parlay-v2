import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiError, api } from "./client";
import type {
  League,
  LeagueDetail,
  Leg,
  Me,
  Round,
  SleeperLeague,
  SleeperLink,
} from "./types";

export const keys = {
  me: ["me"] as const,
  leagues: ["leagues"] as const,
  league: (id: string) => ["league", id] as const,
  currentRound: (leagueId: string) => ["round", "current", leagueId] as const,
  rounds: (leagueId: string) => ["rounds", leagueId] as const,
  importable: (season?: string) => ["importable", season ?? "current"] as const,
};

export function useMe() {
  return useQuery({
    queryKey: keys.me,
    queryFn: async () => {
      try {
        return await api.get<Me>("/me");
      } catch (error) {
        // Not signed in is a normal state, not a failure.
        if (error instanceof ApiError && error.status === 401) return null;
        throw error;
      }
    },
    retry: false,
    staleTime: 60_000,
  });
}

export function useGoogleLogin() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (credential: string) => api.post<Me["user"]>("/auth/google", { credential }),
    onSuccess: () => qc.invalidateQueries(),
  });
}

export function useLogout() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<void>("/auth/logout"),
    onSuccess: () => {
      // Drop every cached query so no signed-in league data outlives the session...
      qc.clear();
      // ...then say outright that we are signed out. Clearing alone only empties the
      // cache; it does not hand the mounted useMe() observer a result, so the app went
      // on rendering the signed-in tree until a reload forced a fresh /me. Seeding null
      // flips it to the login screen on the next render, with no round trip.
      qc.setQueryData<Me | null>(keys.me, null);
    },
  });
}

export function useClaimSleeper() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (username: string) => api.post<SleeperLink>("/me/sleeper", { username }),
    onSuccess: () => qc.invalidateQueries(),
  });
}

export function useMyLeagues() {
  return useQuery({ queryKey: keys.leagues, queryFn: () => api.get<League[]>("/leagues") });
}

export function useImportableLeagues(season: string | undefined, enabled: boolean) {
  return useQuery({
    queryKey: keys.importable(season),
    queryFn: () =>
      api.get<SleeperLeague[]>(`/me/sleeper/leagues${season ? `?season=${season}` : ""}`),
    enabled,
  });
}

export function useImportLeague() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (sleeperLeagueId: string) =>
      api.post<LeagueDetail>("/leagues/import", { sleeper_league_id: sleeperLeagueId }),
    onSuccess: () => qc.invalidateQueries(),
  });
}

export function useDeleteLeague() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (leagueId: string) => api.delete<void>(`/leagues/${leagueId}`),
    onSuccess: () => qc.invalidateQueries(),
  });
}

export function useLeague(leagueId: string | undefined) {
  return useQuery({
    queryKey: keys.league(leagueId!),
    queryFn: () => api.get<LeagueDetail>(`/leagues/${leagueId}`),
    enabled: Boolean(leagueId),
  });
}

export function useCurrentRound(leagueId: string | undefined) {
  return useQuery({
    queryKey: keys.currentRound(leagueId!),
    queryFn: () => api.get<Round | null>(`/leagues/${leagueId}/rounds/current`),
    enabled: Boolean(leagueId),
    // Legs are visible live, so keep the board reasonably fresh while people submit.
    refetchInterval: 30_000,
    refetchOnWindowFocus: true,
  });
}

export function useRoundHistory(leagueId: string | undefined) {
  return useQuery({
    queryKey: keys.rounds(leagueId!),
    queryFn: () => api.get<Round[]>(`/leagues/${leagueId}/rounds`),
    enabled: Boolean(leagueId),
  });
}

function useRoundMutation<TVars>(
  leagueId: string,
  fn: (vars: TVars) => Promise<Round | Leg[] | null>,
) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: keys.currentRound(leagueId) });
      qc.invalidateQueries({ queryKey: keys.rounds(leagueId) });
    },
  });
}

export function useSubmitLeg(leagueId: string, roundId: string | undefined) {
  return useRoundMutation<string>(leagueId, (rawText) =>
    api.put<Round>(`/rounds/${roundId}/legs/me`, { raw_text: rawText }),
  );
}

export function useDeleteLeg(leagueId: string, roundId: string | undefined) {
  return useRoundMutation<void>(leagueId, () => api.delete<Round>(`/rounds/${roundId}/legs/me`));
}

export function useSetLoser(leagueId: string, roundId: string | undefined) {
  return useRoundMutation<string>(leagueId, (memberId) =>
    api.post<Round>(`/rounds/${roundId}/loser`, { member_id: memberId }),
  );
}

export function useRecordResult(leagueId: string, roundId: string | undefined) {
  return useRoundMutation<Record<string, unknown>>(leagueId, (payload) =>
    api.patch<Round>(`/rounds/${roundId}/result`, payload),
  );
}

export function useRefreshRound(leagueId: string) {
  return useRoundMutation<void>(leagueId, () =>
    api.post<Round | null>(`/leagues/${leagueId}/rounds/refresh`),
  );
}

export function useSyncLeague(leagueId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<LeagueDetail>(`/leagues/${leagueId}/sync`),
    onSuccess: () => qc.invalidateQueries(),
  });
}

export function useUpdateSettings(leagueId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: Record<string, unknown>) =>
      api.patch<League>(`/leagues/${leagueId}/settings`, payload),
    onSuccess: () => qc.invalidateQueries(),
  });
}
