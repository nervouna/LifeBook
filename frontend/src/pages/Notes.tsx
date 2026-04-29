import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { NoteListResponse, NoteDetail } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

function SkeletonNoteRow() {
  return (
    <div className="w-full text-left p-3 border-b">
      <div className="h-4 w-40 bg-muted rounded animate-pulse" />
      <div className="flex gap-2 mt-2">
        <div className="h-4 w-14 bg-muted rounded-full animate-pulse" />
        <div className="h-4 w-12 bg-muted rounded-full animate-pulse" />
      </div>
    </div>
  );
}

export default function NotesPage() {
  const [category, setCategory] = useState<string>("");
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const handleCategoryChange = (value: string | null) => setCategory(value ?? "");

  const categories = useQuery({ queryKey: ["categories"], queryFn: () => api.categories() });
  const notes = useQuery<NoteListResponse>({
    queryKey: ["notes", category],
    queryFn: () => api.listNotes(category ? { category } : {}),
  });
  const detail = useQuery<NoteDetail>({
    queryKey: ["note", selectedPath],
    queryFn: () => api.getNote(selectedPath!),
    enabled: !!selectedPath,
  });

  return (
    <div className="flex h-full">
      <div className="w-80 border-r flex flex-col">
        <div className="p-4 space-y-2 border-b">
          <Select value={category} onValueChange={handleCategoryChange}>
            <SelectTrigger><SelectValue placeholder="所有分类" /></SelectTrigger>
            <SelectContent>
              <SelectItem value="">所有分类</SelectItem>
              {categories.data?.categories?.map((c) => (
                <SelectItem key={c} value={c}>{c}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="flex-1 overflow-auto">
          {notes.isLoading ? (
            <>
              <SkeletonNoteRow />
              <SkeletonNoteRow />
              <SkeletonNoteRow />
              <SkeletonNoteRow />
              <SkeletonNoteRow />
            </>
          ) : (
            notes.data?.items?.map((note) => (
              <button
                key={note.path}
                onClick={() => setSelectedPath(note.path)}
                className={`w-full text-left p-3 border-b hover:bg-muted transition-colors ${
                  selectedPath === note.path ? "bg-muted" : ""
                }`}
              >
                <div className="font-medium text-sm">{note.title}</div>
                <div className="text-xs text-muted-foreground mt-1">
                  <Badge variant="outline" className="mr-1">{note.category}</Badge>
                  {note.tags?.slice(0, 2).map((t) => <Badge key={t} variant="secondary" className="mr-1">{t}</Badge>)}
                </div>
              </button>
            ))
          )}
          {notes.data?.items?.length === 0 && (
            <p className="p-4 text-sm text-muted-foreground">暂无笔记</p>
          )}
        </div>
      </div>
      <div className="flex-1 overflow-auto">
        {selectedPath && detail.data ? (
          <div className="p-6 max-w-3xl">
            <h1 className="text-2xl font-bold mb-2">{detail.data.title}</h1>
            <div className="flex gap-2 mb-4">
              <Badge>{detail.data.category}</Badge>
              {detail.data.tags?.map((t) => <Badge key={t} variant="secondary">{t}</Badge>)}
            </div>
            <div className="prose prose-sm max-w-none whitespace-pre-wrap">{detail.data.body}</div>
          </div>
        ) : selectedPath && detail.isLoading ? (
          <div className="p-6 max-w-3xl space-y-4">
            <div className="h-8 w-64 bg-muted rounded animate-pulse" />
            <div className="flex gap-2">
              <div className="h-5 w-16 bg-muted rounded-full animate-pulse" />
              <div className="h-5 w-12 bg-muted rounded-full animate-pulse" />
            </div>
            <div className="space-y-2">
              <div className="h-4 w-full bg-muted rounded animate-pulse" />
              <div className="h-4 w-3/4 bg-muted rounded animate-pulse" />
              <div className="h-4 w-5/6 bg-muted rounded animate-pulse" />
            </div>
          </div>
        ) : (
          <div className="flex items-center justify-center h-full text-muted-foreground">选择一篇笔记查看</div>
        )}
      </div>
    </div>
  );
}
