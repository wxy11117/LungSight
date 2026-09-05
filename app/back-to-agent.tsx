/** Always return to the workspace, including when a subpage was opened directly. */
export default function BackToAgent() {
  return <a className="back-to-agent" href="/agent" aria-label="返回主页（Agent工作台）">
    <span aria-hidden="true">←</span>
    <span>返回主页</span>
  </a>;
}
