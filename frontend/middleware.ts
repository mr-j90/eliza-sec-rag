import { auth } from "@/auth";

/**
 * Gate everything except Auth.js's own routes, the health check, the sign-in
 * page, Next internals, and public assets. Unauthenticated requests are sent
 * to /signin with a callback back to where they were headed.
 */
export default auth((req) => {
  if (!req.auth) {
    const callbackUrl = encodeURIComponent(
      req.nextUrl.pathname + req.nextUrl.search,
    );
    const signInUrl = new URL(
      `/signin?callbackUrl=${callbackUrl}`,
      req.nextUrl.origin,
    );
    return Response.redirect(signInUrl);
  }
});

export const config = {
  matcher: [
    "/((?!api/auth|api/health|signin|_next/static|_next/image|favicon.ico|brand/).*)",
  ],
};
