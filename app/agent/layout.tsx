import AgentAuthGuard from '../AgentAuthGuard';

export default function AgentLayout({ children }: { children: React.ReactNode }) {
  return <AgentAuthGuard>{children}</AgentAuthGuard>;
}
