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

window.addEventListener('scroll',()=>{
  const total = document.documentElement.scrollHeight - innerHeight;
  document.querySelector('.page-progress').style.width = `${total > 0 ? scrollY / total * 100 : 0}%`;
},{passive:true});

const workflowButtons = [...document.querySelectorAll('.workflow-item')];
const workflowPanels = [...document.querySelectorAll('.workflow-preview')];
let workflowIndex = 0;
const activateWorkflow = (index) => {
  workflowIndex = index;
  workflowButtons.forEach((button,itemIndex)=>{
    const active = itemIndex === index;
    button.classList.toggle('active',active);
    button.setAttribute('aria-selected',String(active));
  });
  workflowPanels.forEach((panel,itemIndex)=>panel.classList.toggle('active',itemIndex===index));
};
workflowButtons.forEach((button,index)=>button.addEventListener('click',()=>activateWorkflow(index)));
if (!matchMedia('(prefers-reduced-motion: reduce)').matches) {
  window.setInterval(()=>activateWorkflow((workflowIndex+1)%workflowButtons.length),6500);
}

const platformTabs = [...document.querySelectorAll('[data-platform-tab]')];
const platformPanels = [...document.querySelectorAll('[data-platform-panel]')];
const dagNodes = [...document.querySelectorAll('[data-dag-index]')];
const platformRun = document.querySelector('[data-platform-run]');
let platformStep = 2;
let platformTimer;
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
if (platformRun) platformRun.addEventListener('click',()=>{
  if (platformTimer) return;
  activatePlatform(1);
  platformStep = 0;
  platformRun.disabled = true;
  platformRun.classList.add('running');
  platformRun.querySelector('span').textContent = '流程运行中';
  paintDag();
  platformTimer = window.setInterval(()=>{
    platformStep += 1;
    paintDag();
    if (platformStep >= dagNodes.length) {
      window.clearInterval(platformTimer);
      platformTimer = undefined;
      platformRun.disabled = false;
      platformRun.classList.remove('running');
      platformRun.querySelector('span').textContent = '重新运行';
    }
  },900);
});

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

(() => {
  const graph = document.querySelector('.tech-graph-canvas');
  if (!graph || matchMedia('(prefers-reduced-motion: reduce)').matches || !matchMedia('(pointer: fine)').matches) return;
  const nodes = [...graph.querySelectorAll('.tech-node-wrap')];
  graph.addEventListener('pointermove',event=>{
    const rect = graph.getBoundingClientRect();
    const x = ((event.clientX-rect.left)/rect.width-.5)*2;
    const y = ((event.clientY-rect.top)/rect.height-.5)*2;
    graph.style.setProperty('--center-x',`${x*9}px`);
    graph.style.setProperty('--center-y',`${y*7}px`);
    graph.style.setProperty('--light-x',`${(x+1)*50}%`);
    graph.style.setProperty('--light-y',`${(y+1)*50}%`);
    nodes.forEach((node,index)=>{
      const depth=2.5+(index%4)*1.15;
      node.style.setProperty('--node-x',`${x*depth}px`);
      node.style.setProperty('--node-y',`${y*depth}px`);
    });
  },{passive:true});
  graph.addEventListener('pointerleave',()=>{
    graph.style.setProperty('--center-x','0px');
    graph.style.setProperty('--center-y','0px');
    nodes.forEach(node=>{node.style.setProperty('--node-x','0px');node.style.setProperty('--node-y','0px');});
  });
})();

(() => {
  const canvas = document.querySelector('.interactive-background');
  if (!canvas) return;
  const context = canvas.getContext('2d');
  const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const pointer = { x: innerWidth * .68, y: innerHeight * .34, active: false };
  const ripples = [];
  let particles = [];
  let width = innerWidth;
  let height = innerHeight;
  let time = 0;

  const reset = () => {
    width = innerWidth;
    height = innerHeight;
    const density = Math.min(devicePixelRatio || 1, 1.6);
    canvas.width = Math.round(width * density);
    canvas.height = Math.round(height * density);
    canvas.style.width = `${width}px`;
    canvas.style.height = `${height}px`;
    context.setTransform(density,0,0,density,0,0);
    const count = Math.max(58,Math.min(118,Math.round(width*height/17500)));
    particles = Array.from({length:count},()=>({
      x:Math.random()*width,y:Math.random()*height,
      vx:(Math.random()-.5)*.18,vy:(Math.random()-.5)*.18,
      r:.65+Math.random()*2.15,d:.35+Math.random()*.9,
      p:Math.random()*Math.PI*2,t:Math.random()
    }));
  };

  const renderParticles = () => {
    context.clearRect(0,0,width,height);
    time += reduced ? 0 : .012;
    if (pointer.active) {
      const glow = context.createRadialGradient(pointer.x,pointer.y,0,pointer.x,pointer.y,230);
      glow.addColorStop(0,'rgba(84,178,255,.085)');
      glow.addColorStop(.45,'rgba(54,219,207,.035)');
      glow.addColorStop(1,'rgba(0,0,0,0)');
      context.fillStyle = glow;
      context.fillRect(pointer.x-230,pointer.y-230,460,460);
    }
    particles.forEach(point=>{
      if (!reduced) {
        point.vx += Math.sin(time+point.p)*.0008;
        point.vy += Math.cos(time*.8+point.p)*.0008;
        if (pointer.active) {
          const dx=pointer.x-point.x,dy=pointer.y-point.y,dist=Math.hypot(dx,dy);
          if (dist<190&&dist>1) { const pull=(1-dist/190)*.012*point.d; point.vx+=dx/dist*pull; point.vy+=dy/dist*pull; }
        }
        point.vx*=.992;point.vy*=.992;point.x+=point.vx;point.y+=point.vy;
        if(point.x<-12)point.x=width+12;if(point.x>width+12)point.x=-12;
        if(point.y<-12)point.y=height+12;if(point.y>height+12)point.y=-12;
      }
    });
    for(let i=0;i<particles.length;i++)for(let j=i+1;j<particles.length;j++){
      const a=particles[i],b=particles[j],dist=Math.hypot(a.x-b.x,a.y-b.y);
      if(dist<108){context.beginPath();context.moveTo(a.x,a.y);context.lineTo(b.x,b.y);context.strokeStyle=`rgba(75,157,198,${(1-dist/108)*.075})`;context.lineWidth=.65;context.stroke();}
    }
    particles.forEach(point=>{
      const pulse=reduced?.75:.62+Math.sin(time*3+point.p)*.24;
      const x=point.x+(pointer.active?(pointer.x-width/2)*.008*point.d:0);
      const y=point.y+(pointer.active?(pointer.y-height/2)*.008*point.d:0);
      context.beginPath();context.arc(x,y,point.r*(.85+pulse*.25),0,Math.PI*2);
      context.fillStyle=point.t>.72?`rgba(133,226,255,${.35+pulse*.35})`:`rgba(74,143,255,${.22+pulse*.4})`;
      context.shadowColor=point.t>.72?'#78e8ff':'#4a8fff';context.shadowBlur=8+point.r*5;context.fill();context.shadowBlur=0;
      const dist=Math.hypot(pointer.x-x,pointer.y-y);
      if(pointer.active&&dist<145){context.beginPath();context.moveTo(x,y);context.lineTo(pointer.x,pointer.y);context.strokeStyle=`rgba(91,225,214,${(1-dist/145)*.18})`;context.lineWidth=.8;context.stroke();}
    });
    for(let i=ripples.length-1;i>=0;i--){const ring=ripples[i];ring.life+=.025;context.beginPath();context.arc(ring.x,ring.y,24+ring.life*145,0,Math.PI*2);context.strokeStyle=`rgba(88,231,218,${Math.max(0,.28-ring.life*.28)})`;context.lineWidth=1.2;context.stroke();if(ring.life>=1)ripples.splice(i,1);}
    if(!reduced)requestAnimationFrame(renderParticles);
  };

  addEventListener('resize',reset);
  addEventListener('pointermove',event=>{pointer.x=event.clientX;pointer.y=event.clientY;pointer.active=true;},{passive:true});
  document.documentElement.addEventListener('pointerleave',()=>{pointer.active=false;});
  addEventListener('pointerdown',event=>ripples.push({x:event.clientX,y:event.clientY,life:0}),{passive:true});
  reset();
  renderParticles();
})();
