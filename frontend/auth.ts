import NextAuth from "next-auth";
import Credentials from "next-auth/providers/credentials";

/**
 * Auth.js v5 wiring for a single-user demo build: one account, `demoadmin`,
 * gated by a password supplied through the environment.
 *
 * There is deliberately no fallback password. An unset `DEMO_PASSWORD` disables
 * sign-in entirely rather than admitting a well-known default — a baked-in
 * credential in a repo is worse than a demo that refuses to start.
 *
 * JWT session strategy (no DB adapter) keeps this edge-safe for middleware.
 */

export const DEMO_USERNAME = "demoadmin";

const DEMO_PASSWORD = process.env.DEMO_PASSWORD;

/** True when a password is configured — the sign-in page keys off this. */
export const DEMO_AUTH_ENABLED = Boolean(DEMO_PASSWORD);

const IS_PROD = process.env.NODE_ENV === "production";

const DEMO_USER = {
  id: DEMO_USERNAME,
  name: "Demo Admin",
  // Chat history is filed under this address (see lib/auth.ts ownerKey).
  // example.com is reserved by RFC 2606, so it can never be a real mailbox.
  email: `${DEMO_USERNAME}@example.com`,
};

/**
 * Length-independent string comparison, so a wrong password can't be narrowed
 * down by timing. Uses TextEncoder rather than `node:crypto.timingSafeEqual`
 * because this module is bundled into edge middleware.
 */
function constantTimeEqual(a: string, b: string): boolean {
  const encoder = new TextEncoder();
  const left = encoder.encode(a);
  const right = encoder.encode(b);

  // Fold the length difference into the result and always walk the longer of
  // the two, so the loop count reveals nothing about the expected length.
  let diff = left.length ^ right.length;
  for (let i = 0; i < Math.max(left.length, right.length); i++) {
    diff |= (left[i] ?? 0) ^ (right[i] ?? 0);
  }
  return diff === 0;
}

export const { handlers, auth, signIn, signOut } = NextAuth({
  session: { strategy: "jwt" },
  trustHost: true,
  // AUTH_SECRET is required in production; fall back to a clearly-insecure
  // value in dev only so the app runs without one.
  secret:
    process.env.AUTH_SECRET ??
    (IS_PROD ? undefined : "dev-insecure-secret-change-me"),
  pages: { signIn: "/signin" },
  providers: [
    Credentials({
      id: "demo",
      name: "Demo account",
      credentials: {
        password: { label: "Password", type: "password" },
      },
      authorize(credentials) {
        if (!DEMO_PASSWORD) return null;

        const password = credentials?.password;
        if (typeof password !== "string") return null;
        if (!constantTimeEqual(password, DEMO_PASSWORD)) return null;

        return DEMO_USER;
      },
    }),
  ],
});
