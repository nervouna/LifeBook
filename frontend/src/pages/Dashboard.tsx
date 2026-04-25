import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { StatsResponse, InboxListResponse, NoteListResponse } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Link } from "react-router-dom";

export default function DashboardPage() {
  const stats = useQuery<StatsResponse>({ queryKey: ["stats"], queryFn: () => api.stats() });
  const inbox = useQuery<InboxListResponse>({ queryKey: ["inbox"], queryFn: () => api.listInbox({ status: "inbox" }) });
  const recent = useQuery<NoteListResponse>({ queryKey: ["notes", "recent"], queryFn: () => api.listNotes({ per_page: "5" }) });

  return (
    <div className="p-6 space-y-6">
      <h1 className="text-2xl font-bold">概览</h1>
      <div className="grid grid-cols-3 gap-4">
        <Card>
          <CardHeader className="pb-2"><CardTitle className="text-sm text-muted-foreground">笔记总数</CardTitle></CardHeader>
          <CardContent><div className="text-3xl font-bold">{stats.data?.topic_count ?? "—"}</div></CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2"><CardTitle className="text-sm text-muted-foreground">待处理</CardTitle></CardHeader>
          <CardContent>
            <div className="text-3xl font-bold">{inbox.data?.total ?? "—"}</div>
            {(inbox.data?.total ?? 0) > 0 && (
              <Link to="/inbox" className="text-sm text-primary hover:underline">去处理</Link>
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2"><CardTitle className="text-sm text-muted-foreground">分类</CardTitle></CardHeader>
          <CardContent>
            <div className="flex flex-wrap gap-1">
              {stats.data?.categories?.map((c) => (
                <Badge key={c} variant="secondary">{c}</Badge>
              ))}
            </div>
          </CardContent>
        </Card>
      </div>
      <Card>
        <CardHeader><CardTitle>最近笔记</CardTitle></CardHeader>
        <CardContent>
          {recent.data?.items?.length === 0 ? (
            <p className="text-muted-foreground">暂无笔记</p>
          ) : (
            <div className="space-y-2">
              {recent.data?.items?.map((note) => (
                <Link key={note.path} to={`/notes/${note.path}`} className="block p-2 rounded hover:bg-muted transition-colors">
                  <div className="font-medium">{note.title}</div>
                  <div className="text-sm text-muted-foreground">{note.category} · {note.created?.slice(0, 10)}</div>
                </Link>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
