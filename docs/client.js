const samples = [
  { label:'腺癌', code:'CASE-A01', image:'./public/ct-adeno.png' },
  { label:'大细胞癌', code:'CASE-L02', image:'./public/ct-large.png' },
  { label:'正常肺部', code:'CASE-N03', image:'./public/ct-normal.png' },
  { label:'鳞状细胞癌', code:'CASE-S04', image:'./public/ct-squamous.png' }
];
let active = 0;
const buttons = [...document.querySelectorAll('.case-button')];
const status = document.querySelector('.result-head i');
const imageBox = document.querySelector('.demo-image');
const image = imageBox.querySelector('img');
const resultName = document.querySelector('.result-primary strong');
const resultScore = document.querySelector('.result-primary > span');
const note = document.querySelector('.ai-note p');
const probabilities = [...document.querySelectorAll('.probability')];

function paint() {
  const sample = samples[active];
  document.querySelector('.viewer-toolbar > div:first-child span').textContent = `匿名影像 / ${sample.code}`;
  image.src = sample.image;
  image.alt = `${sample.label}匿名 CT 示例`;
  resultName.textContent = '—';
  resultScore.textContent = '桌面端分析';
  note.textContent = '官网仅浏览示例。请下载桌面端，在本机运行真实模型分析。';
  probabilities.forEach((row)=>{
    row.querySelector('b').textContent = '—';
    row.querySelector('em').style.width = '0%';
  });
  status.textContent = 'PREVIEW';
  status.classList.remove('ready');
}

buttons.forEach((button,index)=>button.addEventListener('click',()=>{
  active = index;
  buttons.forEach((item,i)=>item.classList.toggle('active',i===index));
  paint();
}));

paint();

const workflowButtons = [...document.querySelectorAll('.workflow-item')];
const workflowPanels = [...document.querySelectorAll('.workflow-preview')];
const workflowConsole = document.querySelector('.workflow-console');
const reducedMotion = () => document.documentElement.dataset.motion === 'reduced' || matchMedia('(prefers-reduced-motion: reduce)').matches;
let workflowIndex = 0;
let workflowTimer;
let workflowVisible = !('IntersectionObserver' in window);
let workflowHovered = false;
let workflowFocused = false;
let workflowSelected = false;
const activateWorkflow = (index) => {
  workflowIndex = index;
  workflowButtons.forEach((button,itemIndex)=>{
    const active = itemIndex === index;
    button.classList.toggle('active',active);
    button.setAttribute('aria-selected',String(active));
  });
  workflowPanels.forEach((panel,itemIndex)=>panel.classList.toggle('active',itemIndex===index));
};
const scheduleWorkflow = () => {
  clearTimeout(workflowTimer);
  if (!workflowButtons.length || !workflowVisible || workflowHovered || workflowFocused || workflowSelected || document.hidden || reducedMotion()) return;
  workflowTimer = setTimeout(() => {
    activateWorkflow((workflowIndex + 1) % workflowButtons.length);
    scheduleWorkflow();
  }, 9000);
};
workflowButtons.forEach((button,index)=>button.addEventListener('click',()=>{
  workflowSelected = true;
  activateWorkflow(index);
  scheduleWorkflow();
}));
if (workflowConsole) {
  workflowConsole.addEventListener('pointerenter', () => { workflowHovered = true; scheduleWorkflow(); });
  workflowConsole.addEventListener('pointerleave', () => { workflowHovered = false; scheduleWorkflow(); });
  workflowConsole.addEventListener('focusin', () => { workflowFocused = true; scheduleWorkflow(); });
  workflowConsole.addEventListener('focusout', event => {
    workflowFocused = workflowConsole.contains(event.relatedTarget);
    scheduleWorkflow();
  });
  if ('IntersectionObserver' in window) {
    new IntersectionObserver(entries => {
      workflowVisible = entries[0].isIntersecting;
      scheduleWorkflow();
    }, { threshold: .15 }).observe(workflowConsole);
  }
}
document.addEventListener('visibilitychange', scheduleWorkflow);
window.addEventListener('lungsight:motionchange', scheduleWorkflow);
scheduleWorkflow();

const platformTabs = [...document.querySelectorAll('[data-platform-tab]')];
const platformPanels = [...document.querySelectorAll('[data-platform-panel]')];
const dagNodes = [...document.querySelectorAll('[data-dag-index]')];
const platformRun = document.querySelector('[data-platform-run]');
let platformStep = 2;
let platformTimer;
let platformRunning = false;
const activatePlatform = (index) => {
  platformTabs.forEach((button,itemIndex)=>{
    const active = itemIndex === index;
    button.classList.toggle('active',active);
    button.setAttribute('aria-selected',String(active));
  });
  platformPanels.forEach((panel,itemIndex)=>panel.classList.toggle('active',itemIndex===index));
};
const paintDag = () => {
  dagNodes.forEach((node,index)=>{
    const status = platformStep > index ? 'done' : platformStep === index ? 'running' : 'waiting';
    node.classList.remove('done','running','waiting');
    node.classList.add(status);
    node.querySelector(':scope > b').textContent = status === 'done' ? '完成' : status === 'running' ? '运行中' : '等待';
  });
  const statusText = document.querySelector('[data-platform-panel="1"] .panel-head > span');
  if (statusText) statusText.lastChild.textContent = platformStep >= dagNodes.length ? '本轮流程已完成' : `正在执行 ${Math.min(platformStep+1,dagNodes.length)} / ${dagNodes.length}`;
};
platformTabs.forEach((button,index)=>button.addEventListener('click',()=>activatePlatform(index)));
const finishPlatform = () => {
  clearTimeout(platformTimer);
  platformTimer = undefined;
  platformRunning = false;
  platformStep = dagNodes.length;
  paintDag();
  platformRun.disabled = false;
  platformRun.classList.remove('running');
  platformRun.querySelector('span').textContent = '重新运行';
};
const schedulePlatform = () => {
  clearTimeout(platformTimer);
  if (!platformRunning) return;
  if (reducedMotion()) { finishPlatform(); return; }
  if (document.hidden) return;
  platformTimer = setTimeout(() => {
    platformStep += 1;
    paintDag();
    if (platformStep >= dagNodes.length) finishPlatform();
    else schedulePlatform();
  }, 900);
};
if (platformRun) platformRun.addEventListener('click',()=>{
  if (platformRunning) return;
  platformRunning = true;
  activatePlatform(1);
  platformStep = 0;
  platformRun.disabled = true;
  platformRun.classList.add('running');
  platformRun.querySelector('span').textContent = '流程运行中';
  paintDag();
  schedulePlatform();
});
document.addEventListener('visibilitychange', schedulePlatform);
window.addEventListener('lungsight:motionchange', schedulePlatform);

const techButtons = [...document.querySelectorAll('.tech-node')];
const techPanels = [...document.querySelectorAll('.tech-detail')];
const activateTechNode = (index) => {
  techButtons.forEach((button,itemIndex)=>{
    const active = itemIndex === index;
    button.classList.toggle('active',active);
    button.setAttribute('aria-selected',String(active));
  });
  techPanels.forEach((panel,itemIndex)=>panel.classList.toggle('active',itemIndex===index));
};
techButtons.forEach((button,index)=>button.addEventListener('click',()=>activateTechNode(index)));
