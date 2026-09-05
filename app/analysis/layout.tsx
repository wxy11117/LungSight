import AgentAuthGuard from '../AgentAuthGuard';

export default function AnalysisLayout({ children }: { children: React.ReactNode }) {
  return <AgentAuthGuard>{children}</AgentAuthGuard>;
}
