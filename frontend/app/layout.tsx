import type { Metadata, Viewport } from "next";
import { cookies } from "next/headers";

import { AppSidebar } from "@/components/app-sidebar";
import { AppTopbar } from "@/components/app-topbar";
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar";
import { getCurrentUser, ownerKey } from "@/lib/auth";
import { groupConversations } from "@/lib/chat/history";
import { listConversations } from "@/lib/db/conversations";

import "./globals.css";

export const metadata: Metadata = {
  title: "SEC EDGAR Research Assistant",
  description: "A research assistant for SEC EDGAR filings, powered by AI.",
  icons: {
    icon: "/logo.svg",
  },
};

export const viewport: Viewport = {
  themeColor: "#456A7E",
};

// Applies the persisted theme before paint to avoid a flash.
const themeInit = `(function(){try{var t=localStorage.getItem('theme');if(t==='dark'||(!t&&window.matchMedia('(prefers-color-scheme: dark)').matches)){document.documentElement.classList.add('dark');}}catch(e){}})();`;

export default async function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  const user = await getCurrentUser();
  const cookieStore = await cookies();
  const defaultOpen = cookieStore.get("sidebar_state")?.value !== "false";

  // History lives in the layout so the sidebar shows it on every chat route;
  // router.refresh() after a send is what brings a new conversation into it.
  const groups = user
    ? groupConversations(listConversations(ownerKey(user)))
    : [];

  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeInit }} />
      </head>
      <body className="min-h-screen bg-background text-foreground antialiased">
        {user ? (
          <SidebarProvider defaultOpen={defaultOpen}>
            <AppSidebar groups={groups} />
            <SidebarInset>
              <AppTopbar user={{ name: user.name, email: user.email }} />
              {children}
            </SidebarInset>
          </SidebarProvider>
        ) : (
          children
        )}
      </body>
    </html>
  );
}
