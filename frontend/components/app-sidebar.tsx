"use client";

import { useState, useTransition } from "react";
import Image from "next/image";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { BarChart3, MessageSquare, MoreHorizontal, Pencil, Plus, Trash2 } from "lucide-react";

import {
  deleteConversationAction,
  renameConversationAction,
} from "@/app/chat/actions";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuAction,
  SidebarMenuButton,
  SidebarMenuItem,
  useSidebar,
} from "@/components/ui/sidebar";
import type { ConversationGroup } from "@/lib/chat/history";

import { DeleteConversationDialog } from "./chat/delete-conversation-dialog";
import { RenameConversationDialog } from "./chat/rename-conversation-dialog";

type Target = { id: string; title: string };

export function AppSidebar({ groups }: { groups: ConversationGroup[] }) {
  const pathname = usePathname();
  const router = useRouter();
  const { isMobile, setOpenMobile } = useSidebar();
  const [renaming, setRenaming] = useState<Target | null>(null);
  const [deleting, setDeleting] = useState<Target | null>(null);
  const [pending, startTransition] = useTransition();

  const closeOnMobile = () => {
    if (isMobile) setOpenMobile(false);
  };

  const rename = (id: string, title: string) =>
    startTransition(async () => {
      await renameConversationAction(id, title);
      setRenaming(null);
      router.refresh();
    });

  const remove = (id: string) =>
    startTransition(async () => {
      await deleteConversationAction(id);
      setDeleting(null);
      // Deleting the open conversation would leave a 404 behind — start a new
      // chat instead.
      if (pathname === `/chat/${id}`) router.replace("/chat");
      router.refresh();
    });

  const isEmpty = groups.length === 0;

  return (
    <>
      <Sidebar collapsible="offcanvas">
        <SidebarHeader className="gap-2">
          <Link
            href="/chat"
            onClick={closeOnMobile}
            className="flex items-center gap-2 px-2 py-1.5"
          >
            <Image
              src="/logo.svg"
              alt="LLM Chat"
              width={96}
              height={32}
              priority
              className="h-7 w-auto dark:hidden"
            />
            <Image
              src="/logo-white.svg"
              alt="LLM Chat"
              width={96}
              height={32}
              priority
              className="hidden h-7 w-auto dark:block"
            />
            <span className="text-sm font-semibold">SEC EDGAR Research Assistant</span>
          </Link>

          <Button asChild variant="outline" className="w-full justify-start gap-2">
            <Link href="/chat" onClick={closeOnMobile}>
              <Plus className="size-4" />
              New chat
            </Link>
          </Button>

          {/* Retrieval evaluation runs. Sits next to the chat because the numbers behind an
              answer belong beside the answers, not in a terminal — a diligence tool should be
              able to show its own scores. */}
          <Button
            asChild
            variant={pathname === "/evals" ? "secondary" : "ghost"}
            className="w-full justify-start gap-2"
          >
            <Link href="/evals" onClick={closeOnMobile}>
              <BarChart3 className="size-4" />
              Evals
            </Link>
          </Button>
        </SidebarHeader>

        <SidebarContent>
          {isEmpty && (
            <p className="px-4 py-3 text-xs text-sidebar-foreground/60">
              No conversations yet. Ask something and it will be saved here.
            </p>
          )}

          {groups.map((group) => (
            <SidebarGroup key={group.label}>
              <SidebarGroupLabel>{group.label}</SidebarGroupLabel>
              <SidebarGroupContent>
                <SidebarMenu>
                  {group.conversations.map((conversation) => (
                    <SidebarMenuItem key={conversation.id}>
                      <SidebarMenuButton
                        asChild
                        isActive={pathname === `/chat/${conversation.id}`}
                        tooltip={conversation.title}
                      >
                        <Link
                          href={`/chat/${conversation.id}`}
                          onClick={closeOnMobile}
                        >
                          <MessageSquare />
                          <span className="truncate">{conversation.title}</span>
                        </Link>
                      </SidebarMenuButton>

                      <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                          <SidebarMenuAction
                            showOnHover
                            aria-label={`Actions for ${conversation.title}`}
                          >
                            <MoreHorizontal />
                          </SidebarMenuAction>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent side="right" align="start">
                          <DropdownMenuItem
                            onSelect={() =>
                              setRenaming({
                                id: conversation.id,
                                title: conversation.title,
                              })
                            }
                          >
                            <Pencil />
                            Rename
                          </DropdownMenuItem>
                          <DropdownMenuItem
                            className="text-destructive focus:text-destructive"
                            onSelect={() =>
                              setDeleting({
                                id: conversation.id,
                                title: conversation.title,
                              })
                            }
                          >
                            <Trash2 />
                            Delete
                          </DropdownMenuItem>
                        </DropdownMenuContent>
                      </DropdownMenu>
                    </SidebarMenuItem>
                  ))}
                </SidebarMenu>
              </SidebarGroupContent>
            </SidebarGroup>
          ))}
        </SidebarContent>

        <SidebarFooter>
          <span className="px-2 text-[11px] text-sidebar-foreground/50">
            LLM Chat · v0.1.0
          </span>
        </SidebarFooter>
      </Sidebar>

      <RenameConversationDialog
        target={renaming}
        pending={pending}
        onCancel={() => setRenaming(null)}
        onSubmit={rename}
      />
      <DeleteConversationDialog
        target={deleting}
        pending={pending}
        onCancel={() => setDeleting(null)}
        onConfirm={remove}
      />
    </>
  );
}
