import Image from "next/image";

import { DEMO_AUTH_ENABLED, DEMO_USERNAME } from "@/auth";

import { SignInForm } from "./signin-form";

export default async function SignInPage({
  searchParams,
}: {
  searchParams: Promise<{ callbackUrl?: string }>;
}) {
  const { callbackUrl } = await searchParams;

  return (
    <main className="flex min-h-screen items-center justify-center bg-muted/30 px-6">
      <div className="w-full max-w-sm">
        <div className="mb-8 flex flex-col items-center gap-3 text-center">
          <Image
            src="/logo.svg"
            alt="LLM Chat"
            width={120}
            height={40}
            priority
            className="h-9 w-auto dark:hidden"
          />
          <Image
            src="/logo-white.svg"
            alt="LLM Chat"
            width={120}
            height={40}
            priority
            className="hidden h-9 w-auto dark:block"
          />
          <div>
            <h1 className="text-lg font-semibold tracking-tight">
              Sign in to LLM Chat
            </h1>
            <p className="text-sm text-muted-foreground">
              A streaming AI assistant.
            </p>
          </div>
        </div>

        <SignInForm
          enabled={DEMO_AUTH_ENABLED}
          username={DEMO_USERNAME}
          callbackUrl={callbackUrl ?? "/chat"}
        />
      </div>
    </main>
  );
}
