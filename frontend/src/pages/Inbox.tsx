import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { InboxListResponse } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge, type badgeVariants } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { VariantProps } from "class-variance-authority";
import { Loader2, Play } from "lucide-react";

type BadgeVariant = VariantProps<typeof badgeVariants>["variant"];

const statusColor: Record<string, BadgeVariant> = {
  inbox: "default",
  processing: "secondary",
  processed: "outline",
  skipped: "destructive",
};

function SkeletonRow() {
  return (
    <Card>
      <CardContent className="p-4 flex items-center justify-between">
        <div className="space-y-2">
          <div className="h-4 w-48 bg-muted rounded animate-pulse" />
          <div className="h-3 w-32 bg-muted rounded animate-pulse" />
        </div>
        <div className="h-5 w-16 bg-muted rounded-full animate-pulse" />
      </CardContent>
    </Card>
  );
}

export default function InboxPage() {
  const queryClient = useQueryClient();
  const [ingestUrl, setIngestUrl] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const inbox = useQuery<InboxListResponse>({ queryKey: ["inbox"], queryFn: () => api.listInbox() });
  const ingestMutation = useMutation({
    mutationFn: (url: string) => api.ingest({ url_or_text: url }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["inbox"] });
      queryClient.invalidateQueries({ queryKey: ["stats"] });
      setIngestUrl("");
      setMessage(null);
    },
    onError: (error) => setMessage(error instanceof Error ? error.message : "添加失败"),
  });
  const processMutation = useMutation({
    mutationFn: (path: string) => api.processInboxItem(path),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ["inbox"] });
      queryClient.invalidateQueries({ queryKey: ["notes"] });
      queryClient.invalidateQueries({ queryKey: ["stats"] });
      setMessage(result.skipped ? `已跳过：${result.skipped}` : "处理完成");
    },
    onError: (error) => setMessage(error instanceof Error ? error.message : "处理失败"),
  });
  const processAllMutation = useMutation({
    mutationFn: () => api.processInboxAll(),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ["inbox"] });
      queryClient.invalidateQueries({ queryKey: ["notes"] });
      queryClient.invalidateQueries({ queryKey: ["stats"] });
      setMessage(`处理完成：${result.ok} 成功，${result.skipped} 跳过，${result.failed} 失败`);
    },
    onError: (error) => setMessage(error instanceof Error ? error.message : "批量处理失败"),
  });

  return (
    <div className="p-6 space-y-6">
      <h1 className="text-2xl font-bold">收件箱</h1>
      <Card>
        <CardHeader><CardTitle className="text-sm">添加内容</CardTitle></CardHeader>
        <CardContent>
          <div className="flex gap-2">
            <Input
              placeholder="输入 URL 或文本..."
              value={ingestUrl}
              onChange={(e) => setIngestUrl(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && ingestUrl.trim() && ingestMutation.mutate(ingestUrl.trim())}
            />
            <Button onClick={() => ingestUrl.trim() && ingestMutation.mutate(ingestUrl.trim())} disabled={ingestMutation.isPending}>添加</Button>
          </div>
          {message && <p className="mt-3 text-sm text-muted-foreground">{message}</p>}
        </CardContent>
      </Card>
      {(inbox.data?.items?.length ?? 0) > 0 && (
        <div className="flex justify-end">
          <Button
            variant="outline"
            onClick={() => processAllMutation.mutate()}
            disabled={processMutation.isPending || processAllMutation.isPending}
          >
            {processAllMutation.isPending ? <Loader2 className="animate-spin" /> : <Play />}
            全部处理
          </Button>
        </div>
      )}
      <div className="space-y-2">
        {inbox.isLoading ? (
          <>
            <SkeletonRow />
            <SkeletonRow />
            <SkeletonRow />
          </>
        ) : inbox.data?.items?.length === 0 ? (
          <p className="text-muted-foreground">收件箱为空</p>
        ) : (
          inbox.data?.items?.map((item) => (
            <Card key={item.path}>
              <CardContent className="p-4 flex items-center justify-between gap-4">
                <div>
                  <div className="font-medium">{item.title}</div>
                  <div className="text-sm text-muted-foreground mt-1">{item.source_type} · {item.created?.slice(0, 10)}</div>
                </div>
                <div className="flex items-center gap-2">
                  <Badge variant={statusColor[item.status] ?? "default"}>{item.status}</Badge>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => processMutation.mutate(item.path)}
                    disabled={processMutation.isPending || processAllMutation.isPending}
                  >
                    {processMutation.isPending && processMutation.variables === item.path ? (
                      <Loader2 className="animate-spin" />
                    ) : (
                      <Play />
                    )}
                    处理
                  </Button>
                </div>
              </CardContent>
            </Card>
          ))
        )}
      </div>
    </div>
  );
}
