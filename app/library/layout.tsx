import AgentAuthGuard from '../AgentAuthGuard';

export default function LibraryLayout({ children }: { children: React.ReactNode }) {
  return <AgentAuthGuard>{children}</AgentAuthGuard>;
}
