import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { SearchResponse } from "@/lib/api";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

export default function SearchPage() {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResponse | null>(null);
  const searchMutation = useMutation({
    mutationFn: (q: string) => api.search(q),
    onSuccess: (data) => setResults(data),
  });

  return (
    <div className="p-6 space-y-6">
      <h1 className="text-2xl font-bold">搜索</h1>
      <div className="flex gap-2">
        <Input
          placeholder="语义搜索..."
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && query.trim() && searchMutation.mutate(query.trim())}
        />
        <Button onClick={() => query.trim() && searchMutation.mutate(query.trim())} disabled={searchMutation.isPending}>搜索</Button>
      </div>
      {results && (
        <div className="space-y-2">
          <p className="text-sm text-muted-foreground">找到 {results.results.length} 个结果</p>
          {results.results.map((r) => (
            <Card key={r.path}>
              <CardContent className="p-4">
                <div className="flex items-center justify-between mb-2">
                  <span className="font-medium">{r.title}</span>
                  <Badge variant="outline">{(r.score * 100).toFixed(0)}%</Badge>
                </div>
                <p className="text-sm text-muted-foreground">{r.preview}</p>
                <p className="text-xs text-muted-foreground mt-1">{r.path}</p>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
