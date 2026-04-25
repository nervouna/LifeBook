import { useState, useRef, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { WriterStatus } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";

type ChatMessage = { role: "user" | "assistant"; content: string };

export default function WriterPage() {
  const queryClient = useQueryClient();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [idea, setIdea] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);

  const status = useQuery<WriterStatus>({ queryKey: ["writer-status"], queryFn: () => api.writerStatus(), refetchInterval: 5000 });

  const startMutation = useMutation({
    mutationFn: (idea: string) => api.writerStart(idea),
    onSuccess: (data) => {
      setMessages([{ role: "assistant", content: data.reply }]);
      queryClient.invalidateQueries({ queryKey: ["writer-status"] });
      setIdea("");
    },
  });

  const chatMutation = useMutation({
    mutationFn: (message: string) => api.writerChat(message),
    onMutate: (message) => {
      setMessages((prev) => [...prev, { role: "user", content: message }]);
      setInput("");
    },
    onSuccess: (data) => {
      setMessages((prev) => [...prev, { role: "assistant", content: data.reply }]);
      queryClient.invalidateQueries({ queryKey: ["writer-status"] });
    },
  });

  const publishMutation = useMutation({
    mutationFn: () => api.writerPublish(),
    onSuccess: (data) => {
      setMessages((prev) => [...prev, { role: "assistant", content: data.reply }]);
      queryClient.invalidateQueries({ queryKey: ["writer-status"] });
    },
  });

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [messages]);

  const stageLabel: Record<string, string> = {
    concept: "核心概念", framework: "框架选择", content: "内容延展", review: "审阅修订",
  };

  return (
    <div className="flex flex-col h-full">
      <div className="p-4 border-b flex items-center justify-between">
        <div className="flex items-center gap-2">
          <h1 className="text-xl font-bold">写作</h1>
          {status.data?.active && <Badge>{stageLabel[status.data.stage ?? ""] ?? status.data.stage}</Badge>}
          {status.data?.title && <span className="text-sm text-muted-foreground">— {status.data.title}</span>}
        </div>
        {status.data?.active && (
          <Button variant="outline" size="sm" onClick={() => publishMutation.mutate()}>发布</Button>
        )}
      </div>

      <div ref={scrollRef} className="flex-1 overflow-auto p-4 space-y-4">
        {messages.length === 0 && !status.data?.active && (
          <div className="text-center text-muted-foreground py-12">
            <p className="text-lg mb-4">开始一个新的写作会话</p>
            <div className="flex gap-2 max-w-md mx-auto">
              <Input
                placeholder="输入你的写作想法..."
                value={idea}
                onChange={(e) => setIdea(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && idea.trim() && startMutation.mutate(idea.trim())}
              />
              <Button onClick={() => idea.trim() && startMutation.mutate(idea.trim())} disabled={startMutation.isPending}>开始</Button>
            </div>
          </div>
        )}

        {messages.map((msg, i) => (
          <div key={i} className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}>
            <div className={`max-w-[70%] rounded-lg p-3 ${msg.role === "user" ? "bg-primary text-primary-foreground" : "bg-muted"}`}>
              <div className="text-sm whitespace-pre-wrap">{msg.content}</div>
            </div>
          </div>
        ))}
      </div>

      {status.data?.active && (
        <div className="p-4 border-t">
          <div className="flex gap-2">
            <Input
              placeholder="输入消息..."
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && input.trim() && chatMutation.mutate(input.trim())}
            />
            <Button onClick={() => input.trim() && chatMutation.mutate(input.trim())} disabled={chatMutation.isPending}>发送</Button>
          </div>
        </div>
      )}
    </div>
  );
}
