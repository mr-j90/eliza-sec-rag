"use client";

import { useState } from "react";
import { signIn } from "next-auth/react";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export function SignInForm({
  enabled,
  username,
  callbackUrl,
}: {
  /** False when DEMO_PASSWORD isn't set — nothing can sign in. */
  enabled: boolean;
  username: string;
  callbackUrl: string;
}) {
  const [password, setPassword] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    if (!password || pending) return;
    setPending(true);
    setError(null);

    // redirect: false so a wrong password stays on this page with a message
    // instead of bouncing through Auth.js's own error route.
    const result = await signIn("demo", {
      password,
      redirect: false,
    });

    if (result?.error) {
      setError("Incorrect password.");
      setPassword("");
      setPending(false);
      return;
    }

    window.location.href = callbackUrl;
  };

  if (!enabled) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Sign-in unavailable</CardTitle>
          <CardDescription>No password is configured.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3 text-sm text-muted-foreground">
          <p>
            Set <code className="rounded bg-foreground/10 px-1">DEMO_PASSWORD</code>{" "}
            in <code className="rounded bg-foreground/10 px-1">.env</code> and
            restart. There is no default password by design.
          </p>
          <pre className="overflow-x-auto rounded-md bg-foreground/5 p-3 text-xs">
            <code>
              echo &quot;DEMO_PASSWORD=$(openssl rand -base64 24)&quot; &gt;&gt;
              .env
            </code>
          </pre>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Welcome</CardTitle>
        <CardDescription>
          Signing in as{" "}
          <span className="font-medium text-foreground">{username}</span>.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="space-y-2">
          <Label htmlFor="password">Password</Label>
          <Input
            id="password"
            type="password"
            value={password}
            autoFocus
            autoComplete="current-password"
            aria-invalid={error !== null}
            onChange={(e) => setPassword(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                void submit();
              }
            }}
          />
          {error && <p className="text-sm text-destructive">{error}</p>}
        </div>
        <Button
          className="w-full"
          onClick={() => void submit()}
          disabled={pending || !password}
        >
          {pending ? "Signing in…" : "Sign in"}
        </Button>
      </CardContent>
    </Card>
  );
}
