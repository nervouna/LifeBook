import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";
import { describe, it, expect, vi } from "vitest";
import DashboardPage from "@/pages/Dashboard";

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
  it("renders the page title", () => {
    renderWithProviders(<DashboardPage />);
    expect(screen.getByText("概览")).toBeInTheDocument();
  });

  it("shows skeleton cards while loading", () => {
    const { container } = renderWithProviders(<DashboardPage />);
    const skeletons = container.querySelectorAll(".animate-pulse");
    expect(skeletons.length).toBeGreaterThan(0);
  });
});
