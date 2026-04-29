import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Routes, Route, NavLink } from "react-router-dom";
import { ScrollArea } from "@/components/ui/scroll-area";
import ErrorBoundary from "@/components/ErrorBoundary";
import DashboardPage from "@/pages/Dashboard";
import NotesPage from "@/pages/Notes";
import InboxPage from "@/pages/Inbox";
import SearchPage from "@/pages/Search";
import WriterPage from "@/pages/Writer";
import PodcastPage from "@/pages/Podcast";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: (failureCount, error) => {
        const status = (error as { status?: number })?.status;
        if (status && status >= 400 && status < 500) return false;
        return failureCount < 2;
      },
      staleTime: 30_000,
      refetchOnWindowFocus: false,
    },
  },
});

const navItems = [
  { to: "/", label: "概览", icon: "📊" },
  { to: "/inbox", label: "收件箱", icon: "📥" },
  { to: "/notes", label: "笔记", icon: "📝" },
  { to: "/writer", label: "写作", icon: "✍️" },
  { to: "/search", label: "搜索", icon: "🔍" },
  { to: "/podcast", label: "播客", icon: "🎙️" },
];

function Layout() {
  return (
    <div className="flex h-screen">
      <aside className="w-48 border-r bg-muted/40 flex flex-col">
        <div className="p-4 font-bold text-lg">LifeBook</div>
        <ScrollArea className="flex-1">
          <nav className="space-y-1 p-2">
            {navItems.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.to === "/"}
                className={({ isActive }) =>
                  `flex items-center gap-2 rounded-md px-3 py-2 text-sm transition-colors ${
                    isActive ? "bg-primary text-primary-foreground" : "hover:bg-muted"
                  }`
                }
              >
                <span>{item.icon}</span>
                <span>{item.label}</span>
              </NavLink>
            ))}
          </nav>
        </ScrollArea>
      </aside>
      <main className="flex-1 overflow-auto">
        <Routes>
          <Route path="/" element={<ErrorBoundary><DashboardPage /></ErrorBoundary>} />
          <Route path="/notes/*" element={<ErrorBoundary><NotesPage /></ErrorBoundary>} />
          <Route path="/inbox" element={<ErrorBoundary><InboxPage /></ErrorBoundary>} />
          <Route path="/search" element={<ErrorBoundary><SearchPage /></ErrorBoundary>} />
          <Route path="/writer" element={<ErrorBoundary><WriterPage /></ErrorBoundary>} />
          <Route path="/podcast" element={<ErrorBoundary><PodcastPage /></ErrorBoundary>} />
        </Routes>
      </main>
    </div>
  );
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Layout />
      </BrowserRouter>
    </QueryClientProvider>
  );
}
