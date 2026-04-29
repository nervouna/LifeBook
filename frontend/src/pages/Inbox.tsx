import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { InboxListResponse } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge, type badgeVariants } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { VariantProps } from "class-variance-authority";

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
  const inbox = useQuery<InboxListResponse>({ queryKey: ["inbox"], queryFn: () => api.listInbox() });
  const ingestMutation = useMutation({
    mutationFn: (url: string) => api.ingest({ url_or_text: url }),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["inbox"] }); setIngestUrl(""); },
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
        </CardContent>
      </Card>
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
              <CardContent className="p-4 flex items-center justify-between">
                <div>
                  <div className="font-medium">{item.title}</div>
                  <div className="text-sm text-muted-foreground mt-1">{item.source_type} · {item.created?.slice(0, 10)}</div>
                </div>
                <Badge variant={statusColor[item.status] ?? "default"}>{item.status}</Badge>
              </CardContent>
            </Card>
          ))
        )}
      </div>
    </div>
  );
}
