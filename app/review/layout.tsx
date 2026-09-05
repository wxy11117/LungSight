import AgentAuthGuard from '../AgentAuthGuard';

export default function ReviewLayout({ children }: { children: React.ReactNode }) {
  return <AgentAuthGuard>{children}</AgentAuthGuard>;
}
