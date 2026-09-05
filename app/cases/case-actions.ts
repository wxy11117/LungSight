export type CaseTask = {
  task_id: string;
  created_at: string;
  status: string;
  file_name: string;
  top_class_cn: string;
  top_probability: number;
  reliability_level: string;
  fold_agreement: string;
  quality_status: string;
  priority: string;
  attention_available: boolean;
  reviewer_name: string | null;
  corrected_class_cn: string | null;
  starred_at: string | null;
  archived_at: string | null;
};

export function sortCases<T extends CaseTask>(items: T[]): T[] {
  return [...items].sort((a, b) => {
    const starred = Number(!!b.starred_at) - Number(!!a.starred_at);
    if (starred) return starred;
    if (a.starred_at && b.starred_at && a.starred_at !== b.starred_at) {
      return b.starred_at.localeCompare(a.starred_at);
    }
    return b.created_at.localeCompare(a.created_at) || a.task_id.localeCompare(b.task_id);
  });
}

