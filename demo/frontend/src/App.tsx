import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { CodeGenDemo } from "./components/CodeGenDemo";

const queryClient = new QueryClient();

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <CodeGenDemo />
    </QueryClientProvider>
  );
}
