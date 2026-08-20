"use server";

import { revalidatePath } from "next/cache";

import { requireUserId } from "@/lib/auth";
import {
  deleteConversation,
  renameConversation,
} from "@/lib/db/conversations";

/**
 * Mutations the sidebar calls directly. Server actions rather than route
 * handlers so the conversation list — rendered in the root layout — revalidates
 * as part of the same round trip.
 */

export type ActionResult = { ok: boolean; error?: string };

export async function renameConversationAction(
  id: string,
  title: string,
): Promise<ActionResult> {
  const userId = await requireUserId();
  if (!renameConversation(userId, id, title)) {
    return { ok: false, error: "Could not rename that conversation." };
  }
  revalidatePath("/chat");
  revalidatePath(`/chat/${id}`);
  return { ok: true };
}

export async function deleteConversationAction(
  id: string,
): Promise<ActionResult> {
  const userId = await requireUserId();
  if (!deleteConversation(userId, id)) {
    return { ok: false, error: "Could not delete that conversation." };
  }
  revalidatePath("/chat");
  return { ok: true };
}
