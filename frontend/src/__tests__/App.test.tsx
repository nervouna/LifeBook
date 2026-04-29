import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import App from "@/App";

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

describe("App", () => {
  it("renders the app shell with sidebar", () => {
    render(<App />);
    expect(screen.getByText("LifeBook")).toBeInTheDocument();
  });

  it("renders all navigation links", () => {
    render(<App />);
    expect(screen.getByText("概览")).toBeInTheDocument();
    expect(screen.getByText("收件箱")).toBeInTheDocument();
    expect(screen.getByText("笔记")).toBeInTheDocument();
    expect(screen.getByText("写作")).toBeInTheDocument();
    expect(screen.getByText("搜索")).toBeInTheDocument();
    expect(screen.getByText("播客")).toBeInTheDocument();
  });

  it("renders the dashboard page by default", () => {
    render(<App />);
    expect(screen.getByText("概览")).toBeInTheDocument();
  });
});
