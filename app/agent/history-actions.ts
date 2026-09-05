export type HistoryConversation = {
  conversation_id: string;
  title: string;
  linked_task_id: string | null;
  updated_at: string;
  last_message_at: string;
  message_count: number;
  pinned_at?: string | null;
};

export function sortHistory<T extends HistoryConversation>(items: T[]): T[] {
  return [...items].sort((a, b) => {
    const pinned = Number(!!b.pinned_at) - Number(!!a.pinned_at);
    if (pinned) return pinned;
    if (a.pinned_at && b.pinned_at && a.pinned_at !== b.pinned_at) return b.pinned_at.localeCompare(a.pinned_at);
    return b.last_message_at.localeCompare(a.last_message_at) || a.conversation_id.localeCompare(b.conversation_id);
  });
}

export function menuPosition(x: number, y: number, width: number, height: number, viewportWidth: number, viewportHeight: number) {
  return {
    left: Math.max(8, Math.min(x, viewportWidth - width - 8)),
    top: Math.max(8, Math.min(y, viewportHeight - height - 8)),
  };
}
