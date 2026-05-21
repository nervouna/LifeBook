import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";
import { beforeEach, describe, it, expect, vi } from "vitest";
import DashboardPage from "@/pages/Dashboard";
import { api } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  api: {
    stats: vi.fn(),
    listInbox: vi.fn(),
    listNotes: vi.fn(),
  },
}));

function renderWithProviders(ui: React.ReactNode) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>{ui}</BrowserRouter>
    </QueryClientProvider>
  );
}

describe("DashboardPage", () => {
  beforeEach(() => {
    vi.mocked(api.stats).mockResolvedValue({
      topic_count: 0,
      inbox_count: 0,
      categories: [],
      index_status: "not_indexed",
    });
    vi.mocked(api.listInbox).mockResolvedValue({ items: [], total: 0 });
    vi.mocked(api.listNotes).mockResolvedValue({ items: [], total: 0, page: 1, per_page: 20 });
  });

  it("renders the page title", () => {
    renderWithProviders(<DashboardPage />);
    expect(screen.getByRole("heading", { name: "概览" })).toBeInTheDocument();
  });

  it("shows skeleton cards while loading", () => {
    const { container } = renderWithProviders(<DashboardPage />);
    const skeletons = container.querySelectorAll(".animate-pulse");
    expect(skeletons.length).toBeGreaterThan(0);
  });
});
