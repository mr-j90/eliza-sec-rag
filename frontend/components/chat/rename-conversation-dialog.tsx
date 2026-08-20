"use client";

import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export function RenameConversationDialog({
  target,
  pending,
  onCancel,
  onSubmit,
}: {
  /** The conversation being renamed, or null when the dialog is closed. */
  target: { id: string; title: string } | null;
  pending: boolean;
  onCancel: () => void;
  onSubmit: (id: string, title: string) => void;
}) {
  const [value, setValue] = useState("");

  // Seed the field each time a different conversation is opened for rename.
  useEffect(() => {
    if (target) setValue(target.title);
  }, [target]);

  const submit = () => {
    const title = value.trim();
    if (!target || !title || pending) return;
    onSubmit(target.id, title);
  };

  return (
    <Dialog open={target !== null} onOpenChange={(open) => !open && onCancel()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Rename conversation</DialogTitle>
          <DialogDescription>
            Titles are generated from the first message — give it something you
            will recognise later.
          </DialogDescription>
        </DialogHeader>

        <div className="grid gap-2">
          <Label htmlFor="conversation-title">Title</Label>
          <Input
            id="conversation-title"
            value={value}
            autoFocus
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                submit();
              }
            }}
          />
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={onCancel} disabled={pending}>
            Cancel
          </Button>
          <Button onClick={submit} disabled={pending || !value.trim()}>
            {pending ? "Saving…" : "Save"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
