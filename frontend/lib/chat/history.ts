import { differenceInCalendarDays, isToday, isYesterday } from "date-fns";

import type { ConversationSummary } from "@/lib/db/conversations";

/**
 * Sidebar grouping for the conversation list. Computed on the server and passed
 * down as data: doing the date math in the client component would render
 * against the browser's clock and mismatch the server's HTML on hydration.
 */

export type ConversationGroup = {
  label: string;
  conversations: ConversationSummary[];
};

function bucket(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "Older";
  if (isToday(date)) return "Today";
  if (isYesterday(date)) return "Yesterday";
  if (differenceInCalendarDays(new Date(), date) <= 7) return "Previous 7 days";
  if (differenceInCalendarDays(new Date(), date) <= 30) return "Previous 30 days";
  return "Older";
}

const ORDER = [
  "Today",
  "Yesterday",
  "Previous 7 days",
  "Previous 30 days",
  "Older",
];

/** Bucket conversations by recency, preserving the input order within each. */
export function groupConversations(
  conversations: ConversationSummary[],
): ConversationGroup[] {
  const buckets = new Map<string, ConversationSummary[]>();
  for (const conversation of conversations) {
    const label = bucket(conversation.updatedAt);
    const existing = buckets.get(label);
    if (existing) existing.push(conversation);
    else buckets.set(label, [conversation]);
  }

  return ORDER.filter((label) => buckets.has(label)).map((label) => ({
    label,
    conversations: buckets.get(label)!,
  }));
}
