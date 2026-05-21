import { render, screen } from "@testing-library/react";
import type { PropsWithChildren } from "react";
import { beforeEach, describe, it, expect, vi } from "vitest";
import App from "@/App";
import { api } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  api: {
    stats: vi.fn(),
    listInbox: vi.fn(),
    listNotes: vi.fn(),
    categories: vi.fn(),
    search: vi.fn(),
    writerStatus: vi.fn(),
    doctor: vi.fn(),
  },
}));

vi.mock("@/components/ui/scroll-area", () => ({
  ScrollArea: ({ children, className }: PropsWithChildren<{ className?: string }>) => (
    <div className={className}>{children}</div>
  ),
}));

describe("App", () => {
  beforeEach(() => {
    vi.mocked(api.stats).mockResolvedValue({
      topic_count: 0,
      inbox_count: 0,
      categories: [],
      index_status: "not_indexed",
    });
    vi.mocked(api.listInbox).mockResolvedValue({ items: [], total: 0 });
    vi.mocked(api.listNotes).mockResolvedValue({ items: [], total: 0, page: 1, per_page: 20 });
    vi.mocked(api.categories).mockResolvedValue({ categories: [] });
    vi.mocked(api.writerStatus).mockResolvedValue({ active: false, stage: null, title: null });
    vi.mocked(api.doctor).mockResolvedValue({ checks: [] });
  });

  it("renders the app shell with sidebar", () => {
    render(<App />);
    expect(screen.getByText("LifeBook")).toBeInTheDocument();
  });

  it("renders all navigation links", () => {
    render(<App />);
    expect(screen.getByRole("link", { name: /概览/ })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /收件箱/ })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /笔记/ })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /写作/ })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /搜索/ })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /播客/ })).toBeInTheDocument();
  });

  it("renders the dashboard page by default", () => {
    render(<App />);
    expect(screen.getByRole("heading", { name: "概览" })).toBeInTheDocument();
  });
});
