import "server-only";

import { redirect } from "next/navigation";

import { auth } from "@/auth";

const SIGN_IN = "/signin";

/** Returns the signed-in user, or null. */
export async function getCurrentUser() {
  const session = await auth();
  return session?.user ?? null;
}

/** Gate a server component / route / action on being signed in. */
export async function requireAuth() {
  const session = await auth();
  if (!session?.user) redirect(SIGN_IN);
  return session.user;
}

/**
 * The key chat history is filed under, lower-cased so a differently-cased
 * sign-in still finds the same history. Kept as a seam rather than hardcoded to
 * the demo account, so adding real accounts later doesn't touch the data layer.
 */
export function ownerKey(user: {
  email?: string | null;
  name?: string | null;
}): string {
  const email = user.email?.trim().toLowerCase();
  if (email) return email;
  // No email on the session — fall back to the name so history still works
  // rather than pooling every such user into one shared bucket key.
  return `anon:${user.name?.trim().toLowerCase() ?? "unknown"}`;
}

/** Gate on being signed in and return the history owner key. */
export async function requireUserId(): Promise<string> {
  return ownerKey(await requireAuth());
}
