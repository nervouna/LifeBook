import { useState } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { NoteListResponse, PodcastGenerateResult } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

export default function PodcastPage() {
  const [selectedNote, setSelectedNote] = useState<string>("");
  const [result, setResult] = useState<PodcastGenerateResult | null>(null);

  const notes = useQuery<NoteListResponse>({
    queryKey: ["notes", "podcast"],
    queryFn: () => api.listNotes({ per_page: "100" }),
  });

  const generateMutation = useMutation({
    mutationFn: (notePath: string) => api.generatePodcast(notePath),
    onSuccess: (data) => setResult(data),
  });

  return (
    <div className="p-6 space-y-6">
      <h1 className="text-2xl font-bold">播客</h1>
      <Card>
        <CardHeader><CardTitle className="text-sm">生成单篇播客</CardTitle></CardHeader>
        <CardContent className="space-y-4">
          <Select value={selectedNote} onValueChange={(v) => setSelectedNote(v ?? "")}>
            <SelectTrigger><SelectValue placeholder="选择一篇笔记" /></SelectTrigger>
            <SelectContent>
              {notes.data?.items?.map((note) => (
                <SelectItem key={note.path} value={note.path}>{note.title}</SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button
            onClick={() => selectedNote && generateMutation.mutate(selectedNote)}
            disabled={!selectedNote || generateMutation.isPending}
          >
            {generateMutation.isPending ? "生成中..." : "生成播客"}
          </Button>
          {result && (
            <div className="text-sm text-muted-foreground">
              已生成: {result.path}
              {result.duration ? ` (${result.duration}s)` : ""}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
