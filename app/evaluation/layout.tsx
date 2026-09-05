import AgentAuthGuard from '../AgentAuthGuard';

export default function EvaluationLayout({ children }: { children: React.ReactNode }) {
  return <AgentAuthGuard>{children}</AgentAuthGuard>;
}
