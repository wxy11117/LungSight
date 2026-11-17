'use client';

import { useEffect, useState } from 'react';
import InteractiveBackground from './InteractiveBackground';

const cases = [
  { key: 'adeno', label: '腺癌', code: 'CASE-A01', image: '/ct-adeno.png' },
  { key: 'large', label: '大细胞癌', code: 'CASE-L02', image: '/ct-large.png' },
  { key: 'normal', label: '正常肺部', code: 'CASE-N03', image: '/ct-normal.png' },
  { key: 'squamous', label: '鳞状细胞癌', code: 'CASE-S04', image: '/ct-squamous.png' },
] as const;

const classNames = ['腺癌', '大细胞癌', '正常肺部', '鳞状细胞癌'];
const classKeys = ['adenocarcinoma', 'large_cell_carcinoma', 'normal', 'squamous_cell_carcinoma'] as const;
const apiBaseUrl = process.env.NEXT_PUBLIC_LUNGSIGHT_API_URL ?? 'http://127.0.0.1:8001';

type AnalysisResult = {
  task_id: string;
  status: 'WAITING_FOR_REVIEW';
  input: { file_name: string; image_size: [number, number] };
  model: { name: string; version: string; folds: number; device: string; inference_ms: number };
  prediction: {
    top_class_cn: string;
    probabilities: Record<(typeof classKeys)[number], number>;
  };
  reliability: {
    level: 'STABLE' | 'REVIEW_REQUIRED';
    fold_agreement: string;
    warnings: string[];
  };
  quality_control: {
    status: 'PASS' | 'WARNING';
    warnings: string[];
    metrics: { contrast_std: number; edge_variance: number };
  };
  priority: { level: 'ROUTINE' | 'PRIORITY' | 'HIGH_RISK'; label_cn: string; reasons: string[] };
  attention: { available: boolean; method: string };
  disclaimer: string;
};

function MedicalBrandMark() {
  return <span className="brand-mark" role="img" aria-label="QIONS MED 医学智能品牌标识" />;
}

const workflowSteps = [
  { key: 'import', number: '01', title: '数据批量导入', english: 'Batch Data Intake', icon: '⇩', description: '支持常见图片与基础单帧 CT DICOM 导入，建立本地后台任务。DICOM 像素隐私仍须人工复核。', metrics: [['批量', '按导入限制处理'], ['6', '支持文件格式'], ['LOCAL', '本地处理模式']] },
  { key: 'audit', number: '02', title: '数据库自动检测', english: 'Automated Data Audit', icon: '⌁', description: '自动检查文件完整性、重复影像、尺寸异常和跨数据集泄漏，先保证数据可信。', metrics: [['SHA-256', '文件完整性'], ['pHash', '近重复检测'], ['AUTO', '异常清单生成']] },
  { key: 'compare', number: '03', title: '生成对比分析', english: 'Comparative Analysis', icon: '≋', description: '将当前影像结果与同批次样本、历史记录和类别分布进行结构化对比。', metrics: [['4 类', '概率同步对比'], ['趋势', '历史变化追踪'], ['REPORT', '结构化报告']] },
  { key: 'models', number: '04', title: '五折一致性检查', english: 'Multi-model Cross-check', icon: '⌘', description: '当前版本汇总五折 ResNet18 的概率与投票一致性；其他模型仅为后续研究路线。图中数值为架构示意。', metrics: [['5-fold', '折间一致性'], ['3 路', '候选模型待接入'], ['FLAG', '分歧自动标记']] },
  { key: 'evidence', number: '05', title: '给出判别依据', english: 'Evidence-backed Result', icon: '◎', description: '同时展示分类概率、折间一致性、数据质量和关键影像区域，避免只给黑盒结论。', metrics: [['概率', '四分类置信度'], ['5/5', '折间判断一致'], ['QC', '影像质量状态']] },
  { key: 'guidance', number: '06', title: '诊疗路径参考', english: 'Clinical Pathway Reference', icon: '＋', description: '依据模型结果生成医生复核清单与指南参考入口，最终诊疗决策始终由专业医师完成。', metrics: [['CHECKLIST', '医生复核清单'], ['GUIDELINE', '指南信息入口'], ['HUMAN', '医师最终决策']] },
] as const;

const platformTabs = [
  { key: 'overview', label: '任务总览', icon: '▦' },
  { key: 'dag', label: 'DAG 编排', icon: '⌘' },
  { key: 'monitor', label: '实时监控', icon: '⌁' },
] as const;

const dagSteps = [
  { key: 'intake', number: '01', title: '影像批量导入', meta: 'DICOM / PNG / JPG', icon: '⇩' },
  { key: 'audit', number: '02', title: '数据库自动检测', meta: 'SHA-256 · pHash · QC', icon: '⌁' },
  { key: 'analyse', number: '03', title: '生成对比分析', meta: '四分类概率与历史趋势', icon: '≋' },
  { key: 'verify', number: '04', title: '五折一致性检查', meta: 'ResNet18 × 5 · Consensus', icon: '⌘' },
  { key: 'evidence', number: '05', title: '给出判别依据', meta: '概率 · 一致性 · 质量', icon: '◎' },
  { key: 'review', number: '06', title: '医生复核与路径参考', meta: 'Human in the loop', icon: '＋' },
] as const;

const trainingSources = [
  { name: '本地肺部 CT 四分类库', detail: '腺癌 / 大细胞癌 / 正常肺部 / 鳞癌', status: '已适配', tone: 'ready' },
  { name: 'LIDC-IDRI', detail: '肺结节 CT 与专家标注 · TCIA', status: '规划接入', tone: 'planned' },
  { name: 'NSCLC-Radiomics', detail: '非小细胞肺癌影像与放射组学', status: '规划接入', tone: 'planned' },
  { name: 'CPTAC-LUAD / LSCC', detail: '肺腺癌与肺鳞癌多模态影像资源', status: '接口预留', tone: 'interface' },
  { name: 'IDC / TCIA Catalog', detail: '公共癌症影像数据目录连接器', status: '可扩展', tone: 'interface' },
  { name: '机构 PACS / DICOM', detail: '经授权的院内影像与随访数据', status: '接口预留', tone: 'interface' },
] as const;

const guidelineSources = [
  { region: '中国', name: 'CSCO / 国家级诊疗规范', detail: '筛查、诊断、分期与规范化治疗路径', scope: '版本核验' },
  { region: '北美', name: 'NCCN / ASCO / ACCP', detail: '肺癌多学科诊疗与随访参考体系', scope: '索引接入' },
  { region: '欧洲', name: 'ESMO / ERS / ESTS', detail: '非小细胞与小细胞肺癌临床路径', scope: '索引接入' },
  { region: '国际', name: 'WHO / IASLC', detail: '肿瘤分类、TNM 分期与国际共识', scope: '标准映射' },
  { region: '亚太', name: '区域适配指南', detail: '结合人群差异与本地可及性的参考路径', scope: '规划汇总' },
] as const;

const techNodes = [
  { key: 'lidc', label: 'LIDC-IDRI', category: 'data', categoryLabel: '公开数据', x: 10, y: 26, status: '数据基座', metric: '1,018 例胸部 CT', detail: '用于肺结节检测与标注研究的经典公共影像资源，可作为后续外部训练与泛化验证入口。', source: 'https://www.cancerimagingarchive.net/collection/lidc-idri/' },
  { key: 'nlst', label: 'NLST / LDCT', category: 'data', categoryLabel: '公开数据', x: 14, y: 56, status: '筛查队列', metric: '低剂量 CT', detail: '肺癌筛查研究的重要队列，可支撑风险预测、时间维度随访与跨队列验证设计。', source: 'https://cdas.cancer.gov/nlst/' },
  { key: 'cptac', label: 'CPTAC / TCGA', category: 'data', categoryLabel: '多模态数据', x: 24, y: 82, status: '规划接入', metric: '影像 · 病理 · 组学', detail: '将肺腺癌、肺鳞癌影像与病理、分子数据连接起来，为多模态验证和分型研究预留能力。', source: 'https://www.cancerimagingarchive.net/collection/cptac-luad/' },
  { key: 'pacs', label: 'PACS / DICOM', category: 'data', categoryLabel: '院内数据', x: 39, y: 91, status: '接口预留', metric: '本地匿名化', detail: '面向经授权的院内影像、报告与随访数据，执行匿名化、权限控制和来源追踪。' },
  { key: 'ardila', label: 'Ardila 3D CNN', category: 'paper', categoryLabel: '论文研究', x: 29, y: 17, status: 'Nature Medicine · 2019', metric: '端到端 LDCT 筛查', detail: '研究展示了三维深度学习对低剂量胸部 CT 进行端到端肺癌筛查的路径，为整卷 CT 建模提供论文依据。', source: 'https://www.nature.com/articles/s41591-019-0447-x' },
  { key: 'sybil', label: 'Sybil', category: 'paper', categoryLabel: '论文研究', x: 49, y: 10, status: 'JCO · 2023', metric: '1 年 AUC 0.92 / 0.86 / 0.94', detail: '仅使用一次 LDCT，在 NLST、MGH 与 CGMH 三个独立测试集验证未来肺癌风险；论文同时强调仍需进一步临床研究。', source: 'https://ascopubs.org/doi/10.1200/JCO.22.01345' },
  { key: 'medsam', label: 'MedSAM', category: 'paper', categoryLabel: '论文研究', x: 69, y: 18, status: 'Nature Communications · 2024', metric: '157 万+ 图像-掩膜对', detail: '覆盖 10 种医学影像模态和 30 余种癌症的提示式分割基础模型，可作为未来病灶勾画模块的研究参照。', source: 'https://www.nature.com/articles/s41467-024-44824-z' },
  { key: 'maira', label: 'MAIRA-2', category: 'paper', categoryLabel: '医学 Agent 研究', x: 86, y: 31, status: 'Microsoft Research · 2024', metric: '定位式放射报告', detail: '面向胸部 X 光的多模态研究模型，将影像发现与空间定位关联；此处仅借鉴“证据落点 + 报告草拟”范式。', source: 'https://www.microsoft.com/en-us/research/project/project-maira/' },
  { key: 'resnet', label: 'ResNet18 × 5', category: 'model', categoryLabel: '主分类模型', role: 'primary', x: 36, y: 42, status: '研究预览', metric: 'Accuracy 84.98% · Macro-F1 84.93%', detail: '当前软件采用 research-fivefold-20260902-165455 研究版权重，基于 546 张目录弱标签二维图片训练。内部折外指标仅描述弱标签一致程度，尚未完成患者级与外部临床验证。' },
  { key: 'dinov2', label: 'DINOv2', category: 'model', categoryLabel: '候选研究模型', role: 'auxiliary', x: 28, y: 55, status: '未集成', metric: '候选模型 · 特征对照', detail: '作为不同视觉表征的候选研究路线保留，当前 Windows 安装包未集成此模型，也不提供其在线辅助判别结果。' },
  { key: 'biomedclip', label: 'BiomedCLIP', category: 'model', categoryLabel: '候选研究模型', role: 'auxiliary', x: 35, y: 69, status: '未集成', metric: '医学图文预训练表征', detail: '作为医学图文表征的候选研究路线保留，当前 Windows 安装包未集成此模型，也不提供其交叉核验结果。' },
  { key: 'qc-agent', label: '影像质控 Agent', category: 'agent', categoryLabel: '专病 Agent', x: 84, y: 55, status: '产品架构', metric: '格式 · 重复 · 质量', detail: '在推理前检查格式、匿名化状态、重复样本与影像质量，异常任务不会直接进入分类结论。' },
  { key: 'review-agent', label: '分类复核 Agent', category: 'agent', categoryLabel: '专病 Agent', x: 76, y: 73, status: '产品架构', metric: '多模型一致性', detail: '汇总五折模型和候选模型的概率分布，定位分歧样本，并把不确定性显式交给医生。' },
  { key: 'evidence-agent', label: '循证检索 Agent', category: 'agent', categoryLabel: '专病 Agent', x: 89, y: 84, status: '产品架构', metric: '论文 · 指南 · 版本', detail: '按问题检索论文与指南来源，返回可核验的出处和适用范围，不把语言模型回答当作医学事实。' },
  { key: 'pathchat', label: 'PathChat 范式', category: 'paper', categoryLabel: '医学 Agent 研究', x: 61, y: 88, status: 'Nature · 2024', metric: '病理视觉语言协同', detail: 'PathChat 展示了病理图像与语言交互的研究范式；本项目将其作为未来病理协同思路，而非直接集成或临床背书。', source: 'https://www.nature.com/articles/s41586-024-07618-3' },
  { key: 'doctor', label: '医生最终决策', category: 'governance', categoryLabel: '临床治理', x: 49, y: 96, status: '安全边界', metric: 'Human in the loop', detail: 'Agent 只负责整理、检索、提示与草拟；诊断、分期和个体化治疗方案必须由具备资质的临床团队作出。' },
] as const;

const techCategories = [
  ['data', '数据'], ['paper', '论文'], ['model', '模型'], ['agent', 'Agent'], ['governance', '临床治理'],
] as const;

export default function Home() {
  const [activeCase, setActiveCase] = useState(0);
  const [analysing, setAnalysing] = useState(false);
  const [ready, setReady] = useState(false);
  const [analysisResult, setAnalysisResult] = useState<AnalysisResult | null>(null);
  const [analysisError, setAnalysisError] = useState('');
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [queuedFiles, setQueuedFiles] = useState<File[]>([]);
  const [uploadPreview, setUploadPreview] = useState('');
  const [batchResults, setBatchResults] = useState<AnalysisResult[]>([]);
  const [batchProgress, setBatchProgress] = useState({ done: 0, total: 0 });
  const [progress, setProgress] = useState(0);
  const [activeWorkflow, setActiveWorkflow] = useState(0);
  const [activePlatformTab, setActivePlatformTab] = useState(1);
  const [platformStep, setPlatformStep] = useState(2);
  const [platformRunning, setPlatformRunning] = useState(false);
  const [activeTechNode, setActiveTechNode] = useState(4);
  const sample = cases[activeCase];
  const selectedImage = uploadPreview || sample.image;
  const selectedCode = queuedFiles.length > 1 ? `${uploadFile?.name} +${queuedFiles.length - 1}` : uploadFile?.name || sample.code;
  const scores = classKeys.map((key) => (analysisResult?.prediction.probabilities[key] ?? 0) * 100);

  useEffect(() => {
    const updateProgress = () => {
      const total = document.documentElement.scrollHeight - window.innerHeight;
      setProgress(total > 0 ? (window.scrollY / total) * 100 : 0);
    };
    const observer = new IntersectionObserver((entries) => {
      entries.forEach((entry) => entry.isIntersecting && entry.target.classList.add('is-visible'));
    }, { threshold: 0.12 });
    document.querySelectorAll('.reveal').forEach((node) => observer.observe(node));
    window.addEventListener('scroll', updateProgress, { passive: true });
    updateProgress();
    return () => { window.removeEventListener('scroll', updateProgress); observer.disconnect(); };
  }, []);

  useEffect(() => {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    const timer = window.setInterval(() => setActiveWorkflow((current) => (current + 1) % workflowSteps.length), 6500);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => () => {
    if (uploadPreview) URL.revokeObjectURL(uploadPreview);
  }, [uploadPreview]);

  useEffect(() => {
    const graph = document.querySelector<HTMLElement>('.tech-graph-canvas');
    if (!graph || window.matchMedia('(prefers-reduced-motion: reduce)').matches || !window.matchMedia('(pointer: fine)').matches) return;
    const nodes = Array.from(graph.querySelectorAll<HTMLElement>('.tech-node-wrap'));
    const handlePointerMove = (event: PointerEvent) => {
      const rect = graph.getBoundingClientRect();
      const x = ((event.clientX - rect.left) / rect.width - .5) * 2;
      const y = ((event.clientY - rect.top) / rect.height - .5) * 2;
      graph.style.setProperty('--center-x', `${x * 9}px`);
      graph.style.setProperty('--center-y', `${y * 7}px`);
      graph.style.setProperty('--light-x', `${(x + 1) * 50}%`);
      graph.style.setProperty('--light-y', `${(y + 1) * 50}%`);
      nodes.forEach((node, index) => {
        const depth = 2.5 + (index % 4) * 1.15;
        node.style.setProperty('--node-x', `${x * depth}px`);
        node.style.setProperty('--node-y', `${y * depth}px`);
      });
    };
    const resetPointer = () => {
      graph.style.setProperty('--center-x', '0px');
      graph.style.setProperty('--center-y', '0px');
      nodes.forEach((node) => { node.style.setProperty('--node-x', '0px'); node.style.setProperty('--node-y', '0px'); });
    };
    graph.addEventListener('pointermove', handlePointerMove, { passive: true });
    graph.addEventListener('pointerleave', resetPointer);
    return () => { graph.removeEventListener('pointermove', handlePointerMove); graph.removeEventListener('pointerleave', resetPointer); };
  }, []);

  const chooseCase = (index: number) => {
    if (uploadPreview) URL.revokeObjectURL(uploadPreview);
    setActiveCase(index);
    setUploadFile(null);
    setQueuedFiles([]);
    setUploadPreview('');
    setAnalysisResult(null);
    setBatchResults([]);
    setBatchProgress({ done: 0, total: 0 });
    setAnalysisError('');
    setReady(false);
    setAnalysing(false);
  };

  const chooseUpload = (fileList: FileList | null) => {
    const files = fileList ? Array.from(fileList) : [];
    if (!files.length) return;
    if (uploadPreview) URL.revokeObjectURL(uploadPreview);
    setUploadFile(files[0]);
    setQueuedFiles(files);
    setUploadPreview(URL.createObjectURL(files[0]));
    setAnalysisResult(null);
    setBatchResults([]);
    setBatchProgress({ done: 0, total: files.length });
    setAnalysisError('');
    setReady(false);
  };

  const runAnalysis = async () => {
    setAnalysing(true);
    setReady(false);
    setAnalysisError('');
    setAnalysisResult(null);
    setBatchResults([]);
    try {
      let files = queuedFiles;
      if (!files.length) {
        const sampleResponse = await fetch(sample.image);
        if (!sampleResponse.ok) throw new Error('无法读取内置示例图片');
        files = [new File([await sampleResponse.blob()], `${sample.key}.png`, { type: 'image/png' })];
      }
      setBatchProgress({ done: 0, total: files.length });
      const completed: AnalysisResult[] = [];
      const failures: string[] = [];
      for (const [index, file] of files.entries()) {
        const form = new FormData();
        form.append('file', file);
        const response = await fetch(`${apiBaseUrl}/api/analyze`, { method: 'POST', body: form, credentials: 'include' });
        if (response.status === 401) {
          window.location.href = `/auth?returnTo=${encodeURIComponent('/#demo')}`;
          return;
        }
        const payload = await response.json().catch(() => null) as AnalysisResult | { detail?: string } | null;
        if (response.ok) completed.push(payload as AnalysisResult);
        else failures.push(`${file.name}：${payload && 'detail' in payload && payload.detail ? payload.detail : `返回 ${response.status}`}`);
        setBatchProgress({ done: index + 1, total: files.length });
      }
      if (!completed.length) throw new Error(failures.join('；') || '没有任务成功进入模型');
      setAnalysisResult(completed[0]);
      setBatchResults(completed);
      if (failures.length) setAnalysisError(`成功 ${completed.length} 张，失败 ${failures.length} 张：${failures.join('；')}`);
      setReady(true);
    } catch (error) {
      setAnalysisError(error instanceof Error ? error.message : '分析失败，请确认本地推理服务已启动');
    } finally {
      setAnalysing(false);
    }
  };

  const runPlatformWorkflow = () => {
    if (platformRunning) return;
    setActivePlatformTab(1);
    setPlatformRunning(true);
    setPlatformStep(0);
    let nextStep = 0;
    const timer = window.setInterval(() => {
      nextStep += 1;
      setPlatformStep(nextStep);
      if (nextStep >= dagSteps.length) {
        window.clearInterval(timer);
        setPlatformRunning(false);
      }
    }, 900);
  };

  return (
    <main className="site-shell">
      <InteractiveBackground />
      <div className="page-progress" style={{ width: `${progress}%` }} aria-hidden="true" />
      <div className="ambient ambient-one" aria-hidden="true" />
      <div className="ambient ambient-two" aria-hidden="true" />
      <div className="grid-field" aria-hidden="true" />

      <nav className="nav-wrap" aria-label="主导航">
        <a className="brand" href="#top" aria-label="LungSight 首页">
          <MedicalBrandMark />
          <span>LungSight <b>肺影智析</b></span>
        </a>
        <div className="nav-links">
          <a href="#challenge">医学难题</a>
          <a href="#technology">核心技术</a>
          <a href="#workflow">工作流程</a>
          <a href="#ecosystem">数据生态</a>
          <a href="#tech-graph">技术生态</a>
          <a href="#demo">智能分析</a>
          <a href="#impact">应用价值</a>
        </div>
        <details className="nav-more">
          <summary>更多 <span>＋</span></summary>
          <div className="nav-more-panel">
            <span className="nav-menu-label">页面导航</span>
            <a className="nav-mobile-link" href="#challenge"><i>01</i>医学难题 <em>↗</em></a>
            <a className="nav-mobile-link" href="#technology"><i>02</i>核心技术 <em>↗</em></a>
            <a className="nav-mobile-link" href="#workflow"><i>03</i>工作流程 <em>↗</em></a>
            <a className="nav-mobile-link" href="#ecosystem"><i>04</i>数据生态 <em>↗</em></a>
            <a className="nav-mobile-link" href="#tech-graph"><i>05</i>技术生态 <em>↗</em></a>
            <a className="nav-mobile-link" href="#demo"><i>06</i>智能分析 <em>↗</em></a>
            <a className="nav-mobile-link" href="#impact"><i>07</i>应用价值 <em>↗</em></a>
            <span className="nav-menu-divider" />
            <a href="/review"><i>08</i>医生复核台 <em>↗</em></a>
            <a href="/agent"><i>09</i>医学 Agent <em>↗</em></a>
            <a href="/evaluation"><i>10</i>Agent 评测台 <em>↗</em></a>
            <a href="#responsibility"><i>11</i>责任与安全 <em>↗</em></a>
            <a href="#app-download"><i>12</i>APP 下载 <em>↗</em></a>
            <a href="#creator"><i>13</i>创作者信息 <em>↗</em></a>
          </div>
        </details>
        <a className="nav-cta" href="/agent">进入 Agent <span>↗</span></a>
      </nav>

      <section className="hero" id="top">
        <div className="hero-copy">
          <div className="eyebrow"><i /> 肺部 CT 四分类智能辅助分析系统</div>
          <h1>让每一张肺部 CT<br /><span>更早被看见</span></h1>
          <p className="hero-lead">
            面向肺部 CT 四分类研究与影像复核的软件原型。用本地五折模型整理影像结果，
            连接影像查看、人工记录、循证问答与报告导出。
          </p>
          <div className="hero-actions">
            <a className="primary-button" href="#demo">查看分析演示 <span>→</span></a>
            <a className="text-button" href="#technology">了解模型能力 <span>↓</span></a>
          </div>
          <div className="metric-strip">
            <div><strong>84.98%</strong><span>内部弱标签 OOF 一致率</span></div>
            <div><strong>5-fold</strong><span>稳健概率集成</span></div>
            <div><strong>LOCAL</strong><span>影像在本机处理</span></div>
          </div>
          <p className="metric-note">内部指标不代表临床准确率；患者级独立性与外部泛化尚未验证。</p>
        </div>

        <div className="hero-visual" aria-label="肺部 CT 智能分析示意">
          <div className="orbit orbit-a" /><div className="orbit orbit-b" />
          <div className="scan-card">
            <div className="scan-head"><span><i className="status-dot" /> AI ANALYSIS / 01</span><span>AXIAL · LUNG</span></div>
            <div className="scan-frame">
              <img src="/ct-hero.png" alt="匿名肺部 CT 示例影像" />
              <div className="scan-line" /><span className="target-box" aria-hidden="true" />
              <div className="corner corner-tl" /><div className="corner corner-tr" /><div className="corner corner-bl" /><div className="corner corner-br" />
            </div>
            <div className="scan-result">
              <div><small>MODEL STATUS</small><strong><i /> 分析就绪</strong></div>
              <div><small>PIPELINE</small><strong>ResNet18 × 5</strong></div>
              <a href="#demo" aria-label="查看分析结果">查看结果 ↗</a>
            </div>
          </div>
          <div className="float-chip chip-one"><b>04</b><span>影像类别<br />同步识别</span></div>
          <div className="float-chip chip-two"><b>5-fold</b><span>概率集成<br />研究模型</span></div>
          <div className="float-chip chip-three"><i /> OFFLINE<span>隐私友好推理</span></div>
        </div>
      </section>

      <section className="section challenge-section" id="challenge">
        <div className="section-kicker reveal"><span>01</span> MEDICAL CHALLENGE</div>
        <div className="section-heading reveal">
          <h2>工业社会进程中，<br /><em>肺癌负担仍在上升</em></h2>
          <p>工业化与城市化背景下，吸烟及二手烟、空气污染和职业性致癌物暴露，与人口增长及人口老龄化共同推高肺癌疾病负担。与此同时，早期病灶隐蔽、阅片压力与诊疗资源不均，让更早发现成为迫切难题。</p>
        </div>

        <div className="burden-dashboard reveal">
          <div className="burden-summary">
            <span className="mini-label">GLOBAL LUNG CANCER BURDEN / GLOBOCAN</span>
            <div className="burden-number">248<small>万</small></div>
            <h3>2022 年全球肺癌新发病例</h3>
            <p>约占全球全部新发癌症的 <strong>12.4%</strong>，肺癌重新成为全球新发病例数最多的癌种。</p>
            <div className="burden-facts">
              <div><strong>1 / 8</strong><span>新发癌症病例</span></div>
              <div><strong>1.82 → 2.48</strong><span>2012—2022 / 百万例</span></div>
            </div>
          </div>

          <figure className="burden-chart" aria-labelledby="burden-chart-title">
            <figcaption id="burden-chart-title">
              <span>全球肺癌新发病例估计数</span>
              <small>单位：百万例</small>
            </figcaption>
            <div className="chart-stage">
              <div className="chart-grid" aria-hidden="true"><span>2.5</span><span>2.0</span><span>1.5</span><span>1.0</span><span>0.5</span></div>
              <div className="burden-bars">
                {[
                  { year: '2012', value: 1.82, height: '72.8%' },
                  { year: '2020', value: 2.21, height: '88.4%' },
                  { year: '2022', value: 2.48, height: '99.2%' },
                ].map((item, index) => (
                  <div className="burden-bar" key={item.year}>
                    <strong>{item.value.toFixed(2)}</strong>
                    <i style={{ '--bar-height': item.height, '--bar-delay': `${index * 160}ms` } as React.CSSProperties} />
                    <span>{item.year}</span>
                  </div>
                ))}
              </div>
            </div>
            <p className="chart-note">不同年度 GLOBOCAN 估计值用于呈现病例规模变化；受人口规模与年龄结构影响，不等同于同一人群的年龄标化发病率趋势。</p>
            <div className="chart-source">SOURCE · <a href="https://www.iarc.who.int/reference/cancer-incidence-and-mortality-worldwide-sources-methods-and-major-patterns-in-globocan-2012/" target="_blank" rel="noreferrer">IARC GLOBOCAN 2012</a><span>·</span><a href="https://www.iarc.who.int/news-events/lung-cancer-awareness-month-2022/" target="_blank" rel="noreferrer">2020</a><span>·</span><a href="https://gco.iarc.who.int/media/globocan/factsheets/populations/900-world-fact-sheet.pdf" target="_blank" rel="noreferrer">2022</a></div>
          </figure>
        </div>

        <div className="burden-drivers reveal" aria-label="肺癌疾病负担主要驱动因素">
          <div><span>01</span><strong>吸烟与二手烟</strong><small>首要可干预危险因素</small></div>
          <div><span>02</span><strong>空气与职业暴露</strong><small>污染物、柴油尾气、石棉等</small></div>
          <div><span>03</span><strong>人口老龄化</strong><small>高龄人口规模扩大</small></div>
          <div><span>04</span><strong>人口规模增长</strong><small>推动病例绝对数增加</small></div>
        </div>
        <div className="challenge-grid">
          <article className="challenge-card reveal"><span className="card-index">01</span><div className="line-icon">⌁</div><h3>病灶特征隐蔽</h3><p>早期肺癌在单张 CT 切片中的特征可能细微，易与血管、炎症或正常组织混淆。</p><b>细粒度特征提取</b></article>
          <article className="challenge-card reveal"><span className="card-index">02</span><div className="line-icon">≋</div><h3>大批量阅片压力</h3><p>连续阅片容易造成视觉疲劳，医生需要在有限时间内处理大量影像信息。</p><b>自动化预筛分流</b></article>
          <article className="challenge-card reveal"><span className="card-index">03</span><div className="line-icon">◎</div><h3>诊断资源不均衡</h3><p>基层医疗机构专业影像医师不足，难以持续满足大规模肺癌筛查需求。</p><b>标准化能力下沉</b></article>
        </div>
      </section>

      <section className="section technology-section" id="technology">
        <div className="tech-glow" aria-hidden="true" />
        <div className="section-kicker reveal"><span>02</span> CORE TECHNOLOGY</div>
        <div className="section-heading compact reveal"><h2>把深度学习模型，变成<br /><em>可复用的分析引擎</em></h2><p>模型从数据治理开始，经严格去重五折验证、离线训练和概率集成，最终输出四类可解释概率。</p></div>
        <div className="pipeline reveal">
          {[
            ['01','数据审计','SHA-256 / pHash','剔除重复与跨集合泄漏'],
            ['02','五折训练','ResNet18 × 5','降低单次划分带来的偶然性'],
            ['03','概率集成','Softmax Mean','综合五个模型的稳定判断'],
            ['04','结果交付','CSV + Web UI','类别、概率与流程状态可视化'],
          ].map((item, index) => <div className="pipeline-step" key={item[1]}><span>{item[0]}</span><i className={index === 3 ? 'active' : ''} /><h3>{item[1]}</h3><code>{item[2]}</code><p>{item[3]}</p></div>)}
        </div>
        <div className="advantage-bento">
          <article className="bento-card bento-main reveal"><span className="mini-label">INTERNAL RESEARCH VALIDATION</span><div className="big-number">84.98<small>%</small></div><h3>内部研究验证</h3><p>当前研究版权重基于 546 张目录弱标签二维图片训练，内部 OOF accuracy 84.98%、macro-F1 84.93%。这些数字不代表临床准确率。</p><div className="fold-chart" aria-label="五个模型共同参与概率集成">{[1,2,3,4,5].map((v)=><div key={v}><i style={{height:"24%"}}/><span>F{v}</span></div>)}</div></article>
          <article className="bento-card reveal"><span className="mini-label">PRIVACY FIRST</span><div className="bento-symbol">◉</div><h3>全程离线推理</h3><p>模型权重随软件本地部署，不依赖联网下载，降低医学影像外传风险。</p><span className="status-pill"><i /> LOCAL READY</span></article>
          <article className="bento-card reveal"><span className="mini-label">FOUR-CLASS</span><div className="class-wheel"><span>腺</span><span>大</span><span>正</span><span>鳞</span></div><h3>四类同步判断</h3><p>一次推理输出四类概率，既给出结论，也保留不确定性供医生复核。</p></article>
        </div>
      </section>

      <section className="section workflow-section" id="workflow">
        <div className="section-kicker reveal"><span>03</span> INTELLIGENT WORKFLOW</div>
        <div className="workflow-heading reveal">
          <div><h2>不只是识别，<br /><em>覆盖完整分析流程</em></h2><p>从影像进入系统到医生复核参考，把数据治理、模型判断和结果解释连接为可追踪的工作流。</p></div>
          <div className="workflow-stats"><div><strong>6</strong><span>流程模块</span></div><div><strong>5-fold</strong><span>交叉验证</span></div><div><strong>LOCAL</strong><span>隐私模式</span></div></div>
        </div>
        <div className="workflow-console reveal">
          <div className="workflow-list" role="tablist" aria-label="智能分析工作流">
            {workflowSteps.map((step, index) => (
              <button
                key={step.key}
                className={activeWorkflow === index ? 'workflow-item active' : 'workflow-item'}
                onClick={() => setActiveWorkflow(index)}
                role="tab"
                aria-selected={activeWorkflow === index}
                data-workflow-index={index}
              >
                <span>{step.number}</span><i>{step.icon}</i><div><b>{step.title}</b><small>{step.english}</small></div><em>→</em>
              </button>
            ))}
          </div>
          <div className="workflow-stage">
            {workflowSteps.map((step, index) => (
              <article className={activeWorkflow === index ? 'workflow-preview active' : 'workflow-preview'} key={step.key} data-workflow-panel={index}>
                <div className="workflow-preview-head"><span>WORKFLOW / {step.number}</span><i><b /> ACTIVE MODULE</i></div>
                <div className="workflow-preview-copy"><span>{step.english}</span><h3>{step.title}</h3><p>{step.description}</p></div>

                {step.key === 'import' && <div className="workflow-graphic import-graphic"><div className="file-stream"><span>DICOM</span><span>PNG</span><span>JPG</span></div><div className="flow-lines"><i /><i /><i /></div><div className="data-core"><small>SECURE INTAKE</small><strong>影像任务队列</strong><span><i /> 128 / 128 已就绪</span></div></div>}
                {step.key === 'audit' && <div className="workflow-graphic audit-graphic"><div className="audit-orbit"><span>AI QC</span><i /><i /><i /></div><div className="audit-checks"><span><i>✓</i> 文件完整性<small>PASS</small></span><span><i>✓</i> 近重复影像<small>CHECKED</small></span><span><i>!</i> 尺寸异常<small>2 FLAGGED</small></span></div></div>}
                {step.key === 'compare' && <div className="workflow-graphic compare-graphic"><div className="compare-cards"><div><small>CURRENT</small><strong>88.1%</strong><span>鳞状细胞癌倾向</span></div><i>VS</i><div><small>HISTORY</small><strong>82.6%</strong><span>同类样本均值</span></div></div><div className="compare-bars">{[62,81,44,88,73,92,68].map((value)=><i key={value} style={{height:`${value}%`}} />)}</div></div>}
                {step.key === 'models' && <div className="workflow-graphic models-graphic"><div className="model-nodes"><span>ResNet18<small>5-fold</small></span><span>DINOv2<small>未集成</small></span><span>BiomedCLIP<small>未集成</small></span></div><div className="model-links"><i /><i /><i /></div><div className="consensus-node"><small>CONSENSUS</small><strong>5-fold</strong><span>研究集成</span></div></div>}
                {step.key === 'evidence' && <div className="workflow-graphic evidence-graphic"><div className="evidence-scan"><img src="/ct-squamous.png" alt="判别依据示例 CT" /><span /></div><div className="evidence-stack"><div><span>最高分类概率</span><strong>88.1%</strong></div><div><span>折间判断一致</span><strong>5 / 5</strong></div><div><span>影像质量检测</span><strong>PASS</strong></div></div></div>}
                {step.key === 'guidance' && <div className="workflow-graphic guidance-graphic"><div className="guidance-path"><span><i>1</i>影像科医生复核<small>必须</small></span><span><i>2</i>结合临床与病理信息<small>建议</small></span><span><i>3</i>进入规范化诊疗路径<small>指南参考</small></span></div><div className="human-decision"><b>HUMAN IN THE LOOP</b><span>不自动开具诊断或处方</span></div></div>}

                <div className="workflow-metrics">{step.metrics.map((metric)=><div key={metric[1]}><strong>{metric[0]}</strong><span>{metric[1]}</span></div>)}</div>
                <p className="workflow-safety">该模块提供辅助分析和信息整理，不能替代医生诊断、病理检查或个体化治疗决策。</p>
              </article>
            ))}
          </div>
        </div>

        <div className="platform-intro reveal" id="workflow-platform">
          <div><span className="mini-label">VISUAL WORKFLOW MANAGEMENT</span><h2>可视化工作流，<br /><em>一站式管理</em></h2><p>以下为工作流架构交互示意，任务数量、吞吐与运行日志为展示数据。实际桌面端已支持后台分析、取消与继续、重启恢复和人工复核。</p></div>
          <div className="platform-tabs" role="tablist" aria-label="工作流管理平台视图">
            {platformTabs.map((tab, index) => <button key={tab.key} className={activePlatformTab === index ? 'active' : ''} onClick={() => setActivePlatformTab(index)} role="tab" aria-selected={activePlatformTab === index} data-platform-tab={index}><i>{tab.icon}</i>{tab.label}</button>)}
          </div>
        </div>

        <div className="platform-browser reveal">
          <div className="platform-browser-bar"><div><i /><i /><i /></div><span>lungsight.local / workflow</span><button className={platformRunning ? 'running' : ''} onClick={runPlatformWorkflow} disabled={platformRunning} data-platform-run><i /><span>{platformRunning ? '流程运行中' : platformStep >= dagSteps.length ? '重新运行' : '模拟运行'}</span></button></div>
          <div className="platform-window">
            <aside className="platform-rail" aria-hidden="true"><b>LS</b><i>▦</i><i className="active">⌘</i><i>◎</i><i>⌁</i><span /></aside>
            <div className="platform-workspace">
              <section className={activePlatformTab === 0 ? 'platform-panel active' : 'platform-panel'} data-platform-panel={0}>
                <div className="panel-head"><div><small>WORKFLOW OVERVIEW</small><h3>今日分析任务</h3></div><span><i /> 系统运行正常</span></div>
                <div className="overview-metrics"><article><span>任务队列</span><strong>128</strong><small>12 个批次</small></article><article><span>已完成分析</span><strong>96</strong><small>75.0% COMPLETE</small></article><article><span>待医生复核</span><strong>14</strong><small>HIGH PRIORITY 3</small></article><article><span>模型服务</span><strong>5 / 5</strong><small>ALL ONLINE</small></article></div>
                <div className="overview-table"><div className="overview-table-head"><span>任务批次</span><span>当前阶段</span><span>进度</span><span>状态</span></div>{[['CT-2026-0826-A','五折一致性检查','82%','运行中'],['CT-2026-0826-B','医生复核','100%','待复核'],['CT-2026-0825-F','结果归档','100%','已完成']].map((row,index)=><div className="overview-row" key={row[0]}><strong>{row[0]}</strong><span>{row[1]}</span><i><em style={{width:row[2]}} /></i><b className={index===0?'running':index===1?'review':'done'}>{row[3]}</b></div>)}</div>
              </section>

              <section className={activePlatformTab === 1 ? 'platform-panel active' : 'platform-panel'} data-platform-panel={1}>
                <div className="panel-head"><div><small>CLINICAL ANALYSIS DAG</small><h3>肺部 CT 智能分析流程</h3></div><span><i /> {platformRunning ? `正在执行 ${Math.min(platformStep + 1, dagSteps.length)} / ${dagSteps.length}` : platformStep >= dagSteps.length ? '本轮流程已完成' : '流程编排就绪'}</span></div>
                <div className="dag-canvas">
                  <div className="dag-grid" aria-label="六步工作流运行状态">
                    {dagSteps.map((step,index) => {
                      const status = platformStep > index ? 'done' : platformStep === index ? 'running' : 'waiting';
                      return <article className={`dag-node ${status}`} key={step.key} data-dag-index={index}><span>{step.number}</span><i>{step.icon}</i><div><strong>{step.title}</strong><small>{step.meta}</small></div><b>{status === 'done' ? '完成' : status === 'running' ? '运行中' : '等待'}</b></article>;
                    })}
                  </div>
                  <div className="dag-legend"><span><i className="done" />完成</span><span><i className="running" />运行中</span><span><i />等待</span></div>
                </div>
              </section>

              <section className={activePlatformTab === 2 ? 'platform-panel active' : 'platform-panel'} data-platform-panel={2}>
                <div className="panel-head"><div><small>REAL-TIME OBSERVABILITY</small><h3>模型与任务实时监控</h3></div><span><i /> 近 60 分钟</span></div>
                <div className="monitor-grid"><article><div className="monitor-card-head"><span>任务吞吐</span><b>12.8<small> 张 / 秒</small></b></div><div className="throughput-chart">{[28,42,36,57,49,68,61,74,69,82,76,88,72,91,84,78,93,86].map((value,index)=><i key={index} style={{height:`${value}%`}} />)}</div><div className="monitor-axis"><span>-60m</span><span>-30m</span><span>NOW</span></div></article><article><div className="monitor-card-head"><span>五折模型健康度</span><b>99.9<small>%</small></b></div><div className="model-health">{[98,100,99,100,99].map((value,index)=><div key={index}><span>FOLD {index+1}</span><i><em style={{width:`${value}%`}} /></i><b>{value}%</b></div>)}</div></article><article className="monitor-log"><div className="monitor-card-head"><span>运行日志</span><b className="live"><i /> LIVE</b></div>{[['12:46:08','MODEL','Fold 05 推理完成'],['12:46:07','QC','影像质量检测通过'],['12:46:05','QUEUE','任务 CT-A128 已载入'],['12:46:02','AUDIT','未发现跨集合重复']].map((item)=><p key={item[0]}><time>{item[0]}</time><b>{item[1]}</b><span>{item[2]}</span></p>)}</article></div>
              </section>
            </div>
          </div>
        </div>
      </section>

      <section className="section ecosystem-section" id="ecosystem">
        <div className="section-kicker reveal"><span>04</span> DATA &amp; GUIDELINE ECOSYSTEM</div>
        <div className="ecosystem-heading reveal">
          <div><h2>多种数据库训练支持，<br /><em>全球诊疗路径汇总</em></h2><p>通过标准化数据连接器扩展训练来源，同时建立全球指南参考索引，让模型能力、数据来源与循证路径保持可追踪。</p></div>
          <div className="ecosystem-summary"><div><strong>6</strong><span>数据源接口</span></div><div><strong>5</strong><span>指南体系</span></div><div><strong>100%</strong><span>来源状态标注</span></div></div>
        </div>

        <div className="ecosystem-grid reveal">
          <div className="source-column">
            <div className="source-column-head"><div><i>◫</i><span><b>训练数据库支持</b><small>TRAINING DATA SOURCES</small></span></div><em>{trainingSources.length} SOURCES</em></div>
            <div className="source-list">
              {trainingSources.map((source, index) => <div className="source-row" key={source.name}><span>{String(index + 1).padStart(2, '0')}</span><div><strong>{source.name}</strong><small>{source.detail}</small></div><em className={source.tone}>{source.status}</em></div>)}
            </div>
          </div>
          <div className="source-column guideline-column">
            <div className="source-column-head"><div><i>◎</i><span><b>全球诊疗指南索引</b><small>GLOBAL CLINICAL REFERENCES</small></span></div><em>{guidelineSources.length} REGIONS</em></div>
            <div className="source-list">
              {guidelineSources.map((source, index) => <div className="source-row guideline-row" key={source.region}><span>{String(index + 1).padStart(2, '0')}</span><i>{source.region}</i><div><strong>{source.name}</strong><small>{source.detail}</small></div><em>{source.scope}</em></div>)}
            </div>
            <div className="guideline-more"><span>＋</span><p><b>持续更新机制</b><small>记录来源、地区、发布日期和适用范围；正式应用前必须核验最新版本。</small></p></div>
          </div>
        </div>

        <div className="evidence-loop reveal">
          <span className="mini-label">EVIDENCE GOVERNANCE LOOP</span>
          <div><span><i>01</i><b>来源核验</b><small>数据授权与指南版本</small></span><em>→</em><span><i>02</i><b>本地适配</b><small>人群、设备与临床条件</small></span><em>→</em><span><i>03</i><b>医生复核</b><small>形成最终诊疗决策</small></span></div>
          <p>数据库名称仅表示连接与扩展规划；诊疗指南模块提供来源索引和信息整理，不复制受限内容，也不自动生成个体化治疗方案。</p>
        </div>
      </section>

      <section className="section tech-graph-section" id="tech-graph">
        <div className="section-kicker reveal"><span>05</span> RESEARCH &amp; AGENT ECOSYSTEM</div>
        <div className="tech-graph-heading reveal">
          <div><h2>论文证据与诊疗 Agent，<br /><em>组成可演进的技术生态</em></h2><p>以当前五折分类模型为核心，连接公开数据、医学影像研究与肺癌专病工作流；每个节点都标注来源或产品状态。</p></div>
          <div className="tech-graph-stats"><div><strong>5</strong><span>研究锚点</span></div><div><strong>4</strong><span>数据层节点</span></div><div><strong>3</strong><span>模型研究路线</span></div></div>
        </div>

        <div className="tech-graph-shell reveal">
          <div className="tech-graph-toolbar">
            <span><i /> LUNGSIGHT TECHNOLOGY MAP</span>
            <div>{techCategories.map(([key, label]) => <span key={key}><i className={key} />{label}</span>)}</div>
          </div>
          <div className="tech-graph-canvas" role="tablist" aria-label="肺癌智能诊疗技术生态节点">
            <div className="tech-sparks" aria-hidden="true">{Array.from({ length: 14 }, (_, index) => <i key={index} />)}</div>
            <div className="tech-center" aria-hidden="true"><i /><span>LS</span><b>LungSight</b><small>专病协同引擎</small></div>
            {techNodes.map((node, index) => {
              const dx = 50 - node.x;
              const dy = (50 - node.y) * .56;
              const distance = Math.sqrt(dx * dx + dy * dy);
              const angle = Math.atan2(dy, dx) * 180 / Math.PI;
              const roleClass = 'role' in node ? ` ${node.role}` : '';
              return <div className="tech-node-wrap" key={node.key} style={{ left: `${node.x}%`, top: `${node.y}%` }}>
                <i className={`tech-link ${node.category}`} style={{ width: `${distance}%`, transform: `rotate(${angle}deg)` }} />
                <button
                  className={activeTechNode === index ? `tech-node ${node.category}${roleClass} active` : `tech-node ${node.category}${roleClass}`}
                  onClick={() => setActiveTechNode(index)}
                  role="tab"
                  aria-selected={activeTechNode === index}
                  data-tech-index={index}
                ><i /><span>{node.label}</span><small>{node.categoryLabel}</small></button>
              </div>;
            })}
          </div>
          <div className="tech-detail-dock">
            {techNodes.map((node, index) => <article className={activeTechNode === index ? 'tech-detail active' : 'tech-detail'} key={node.key} data-tech-panel={index}>
              <div><span className={`tech-detail-type ${node.category}${'role' in node ? ` ${node.role}` : ''}`}>{node.categoryLabel}</span><small>NODE / {String(index + 1).padStart(2, '0')}</small></div>
              <h3>{node.label}</h3><strong>{node.metric}</strong><p>{node.detail}</p>
              <div className="tech-detail-foot"><span><i /> {node.status}</span>{'source' in node && node.source && <a href={node.source} target="_blank" rel="noreferrer">查看研究来源 ↗</a>}</div>
            </article>)}
            <aside><span className="mini-label">CLINICAL SAFETY BOUNDARY</span><h3>Agent 是协作层，<br />不是自动诊疗终点。</h3><p>研究模型、公开数据与指南索引用于支撑辅助分析。系统不自动下诊断、不生成处方，所有患者级结论均需医生结合病理、分期和临床信息确认。</p><div><span><i>01</i>来源可核验</span><span><i>02</i>模型可追踪</span><span><i>03</i>医生最终决策</span></div></aside>
          </div>
        </div>
        <div className="model-selection-note reveal"><span>MODEL SELECTION</span><strong>ResNet18 主判别</strong><i>＋</i><strong>DINOv2 研究路线</strong><i>＋</i><strong>BiomedCLIP 研究路线</strong><p>当前安装包仅集成五折 ResNet18 研究模型，使用平均概率与温度缩放（T=0.56）。DINOv2 与 BiomedCLIP 尚未集成；病例级结论仍被阻断。模型状态与验证范围以仓库模型卡为准。</p></div>
        <p className="tech-source-note reveal">图中 Ardila、Sybil、MedSAM、MAIRA-2 与 PathChat 为研究参考；DINOv2 与 BiomedCLIP 为未集成的候选路线。当前软件只使用五折 ResNet18 进行本地研究推理，未获得临床批准。</p>
      </section>

      <section className="section demo-section" id="demo">
        <div className="section-kicker reveal"><span>06</span> INTERACTIVE DEMO</div>
        <div className="section-heading reveal"><h2>一张影像，<br /><em>一次完整分析</em></h2><p>选择匿名示例影像，体验从图像载入、模型推理到四分类概率呈现的完整软件工作流。</p></div>
        <div className="demo-app reveal">
          <aside className="case-sidebar">
            <div className="app-brand"><MedicalBrandMark /><div><b>LungSight Console</b><small>RESEARCH PROTOTYPE</small></div></div>
            <span className="aside-title">示例影像</span>
            {cases.map((item,index)=><button className={activeCase===index?'case-button active':'case-button'} key={item.key} onClick={()=>chooseCase(index)}><span>{String(index+1).padStart(2,'0')}</span><div><b>{item.label}</b><small>{item.code}</small></div><i>›</i></button>)}
            <label className="upload-button"><span>＋ 上传或批量选择 CT</span><small>{queuedFiles.length ? `已加入 ${queuedFiles.length} 张影像` : 'PNG / JPG / BMP / TIFF · 单张20MB内'}</small><input type="file" multiple accept=".png,.jpg,.jpeg,.bmp,.tif,.tiff,image/png,image/jpeg,image/bmp,image/tiff" onChange={(event)=>chooseUpload(event.target.files)} /></label>
            <div className="local-box"><i /> 五折模型在本机完成推理<small>LOCAL INFERENCE · NO CLOUD UPLOAD</small></div>
          </aside>
          <div className="viewer-panel">
            <div className="viewer-toolbar"><div><span>当前影像 / {selectedCode}</span><b>2D CT IMAGE</b></div><div className="toolbar-actions"><span>RGB INPUT</span><span>224 MODEL INPUT</span><button aria-label="全屏预览">⌗</button></div></div>
            <div className={analysing?'demo-image analysing':'demo-image'}>
              <img src={selectedImage} alt={uploadFile ? '用户上传的二维 CT 图片' : `${sample.label}CT 示例`} />
              <div className="scan-line" /><div className="coordinate x">R</div><div className="coordinate y">A</div>
              <div className="image-meta">{analysisResult ? `${analysisResult.input.image_size[0]} × ${analysisResult.input.image_size[1]}` : 'IMAGE READY'}<br />SLICE 01/01</div>
            </div>
            <div className="viewer-footer"><span><i /> RESEARCH 2D CT</span><span>科研原型 · 非患者诊断</span></div>
          </div>
          <aside className="result-panel">
            <div className="result-head"><span>AI 分析结果</span><i className={ready?'ready':''}>{analysing?'RUNNING':ready?'READY':'WAIT'}</i></div>
            <div className="result-primary"><small>内部最高排序（非诊断）</small><strong>{ready?analysisResult?.prediction.top_class_cn:'—'}</strong><span>{ready?`${Math.max(...scores).toFixed(1)}%`:'等待分析'}</span></div>
            <div className="probability-list">
              {classNames.map((name,index)=><div className="probability" key={name}><div><span>{name}</span><b>{ready?`${scores[index].toFixed(1)}%`:'0.0%'}</b></div><i><em style={{width:ready?`${scores[index]}%`:'0%'}} /></i></div>)}
            </div>
            {analysisResult && <div className="result-meta"><span>五折一致性 <b>{analysisResult.reliability.fold_agreement}</b></span><span>质控状态 <b>{analysisResult.quality_control.status === 'PASS' ? '通过' : '有提示'}</b></span><span>复核优先级 <b>{analysisResult.priority.label_cn}</b></span><span>注意力解释 <b>{analysisResult.attention.available ? 'Grad-CAM 已生成' : '不可用'}</b></span></div>}
            {batchProgress.total > 1 && <div className="batch-progress"><div><span>批量任务队列</span><b>{batchProgress.done} / {batchProgress.total}</b></div><i><em style={{width:`${batchProgress.total ? batchProgress.done / batchProgress.total * 100 : 0}%`}} /></i>{batchResults.length > 0 && <small>{batchResults.length} 个任务已进入医生复核队列</small>}</div>}
            <div className={analysisError?'ai-note error':'ai-note'}><span>{analysisError?'!':'AI'}</span><p>{analysisError || (analysisResult ? (analysisResult.reliability.warnings.length ? analysisResult.reliability.warnings.join('；') : '五折输出稳定。该结果仍必须由专业医师复核。') : '选择内置示例或上传二维图片，运行本地五折 ResNet18 模型。')}</p></div>
            {analysisResult && <><a className="review-link" href={`/review?task=${analysisResult.task_id}`}><span>进入医生复核工作台</span><i>↗</i></a><a className="review-link agent-explain-link" href={`/agent?task=${analysisResult.task_id}`}><span>让Agent解释判断依据</span><i>↗</i></a></>}
            <button className="run-button" onClick={runAnalysis} disabled={analysing}><span>{analysing?(batchProgress.total>1?`队列分析中 ${batchProgress.done}/${batchProgress.total}`:'质控与五折模型正在运行…'):ready?'重新运行真实分析':queuedFiles.length>1?`批量分析 ${queuedFiles.length} 张影像`:'运行真实模型分析'}</span><i>{analysing?'···':'→'}</i></button>
            <p className="demo-disclaimer">演示仅接受与训练格式相近的二维 CT 图片；数据域一致性、患者级独立性与外部泛化尚未验证。结果不构成临床诊断意见。</p>
          </aside>
        </div>
      </section>

      <section className="section impact-section" id="impact">
        <div className="section-kicker reveal"><span>07</span> IMPACT &amp; ROADMAP</div>
        <div className="section-heading reveal"><h2>从单次影像分析，<br /><em>走向持续生长的软件</em></h2><p>以肺部 CT 四分类为起点，建立可扩展的影像分析底座，连接算法、医生与基层筛查场景。</p></div>
        <div className="impact-grid">
          <article className="impact-card reveal"><span>效率</span><strong>更快预筛</strong><p>批量完成影像初筛，让医生把更多时间投入疑难病例与最终决策。</p></article>
          <article className="impact-card reveal"><span>一致性</span><strong>量化输出</strong><p>用统一流程输出类别概率，减少纯经验判断带来的波动。</p></article>
          <article className="impact-card reveal"><span>可及性</span><strong>能力下沉</strong><p>离线部署与轻量模型让基层机构也能获得智能辅助分析能力。</p></article>
          <article className="impact-card reveal"><span>成长性</span><strong>模型扩展</strong><p>已支持 Grad-CAM 注意力图与人工标记；病灶分割、多模态病历和更多疾病类别仍需后续研究。</p></article>
        </div>
        <div className="roadmap reveal">
          <div className="roadmap-copy"><span className="mini-label">PRODUCT DEVELOPMENT ROADMAP</span><h3>Agent 回归验收已接通，<br />下一步验证真实泛化。</h3><p>beta.3 已完成前端回归、包内运行与 8 项工作流验收，覆盖任务恢复、影像查看、标记和报告。工程验收不代表临床验证；下一阶段仍需独立外部数据评估。</p><a href="/evaluation">查看 Agent 评测 →</a></div>
          <div className="roadmap-track">{[['NOW','循证 Agent','检索 · 引用 · 拒答 · 归档'],['NEXT','外部验证','独立数据与分层评估'],['FUTURE','临床研究','多中心前瞻性验证']].map((item,i)=><div key={item[0]} className={i===0?'current':''}><i>{i+1}</i><span>{item[0]}</span><strong>{item[1]}</strong><p>{item[2]}</p></div>)}</div>
        </div>
      </section>

      <section className="section responsibility-section" id="responsibility">
        <div className="responsibility-glow" aria-hidden="true" />
        <div className="section-kicker reveal"><span>08</span> RESPONSIBLE MEDICAL AI</div>
        <div className="responsibility-heading reveal">
          <div><span className="responsibility-label">♢ 负责任地使用医学 AI</span><h2>辅助医师，<br /><em>不替代医师</em></h2><p>智能体的价值是帮助专业人员更高效地整理影像信息、发现分歧和追踪证据，而不是绕过临床判断。明确边界，是产品可信度的一部分。</p></div>
          <div className="responsibility-status"><i /><span><small>PRODUCT STATUS</small><b>科研与产品验证原型</b></span><em>NON-CLINICAL</em></div>
        </div>

        <div className="responsibility-cards">
          <article className="responsibility-card reveal"><span className="responsibility-icon">◇</span><em>01</em><h3>定位为辅助分析工具</h3><p>输出内容是基于当前模型与输入影像形成的概率性参考，只用于支持医师开展筛查、复核和科研分析，不构成独立医学结论。</p><b>DECISION SUPPORT ONLY</b></article>
          <article className="responsibility-card reveal"><span className="responsibility-icon">▣</span><em>02</em><h3>保留人工复核环节</h3><p>诊断、分期、病理判断和治疗选择必须由具备相应资质的医师结合完整病史、检查结果与现行规范综合决定。</p><b>HUMAN OVERSIGHT REQUIRED</b></article>
          <article className="responsibility-card reveal"><span className="responsibility-icon">◎</span><em>03</em><h3>明确产品适用边界</h3><p>当前版本尚未完成真实临床场景验证和医疗器械监管审批，不用于急危重症处置，不可直接生成处方或个体化治疗方案。</p><b>RESEARCH PROTOTYPE</b></article>
        </div>

        <div className="privacy-kicker reveal"><span>▢</span> 数据安全与过程治理</div>
        <div className="responsibility-lower reveal">
          <div className="privacy-card"><span>⌂</span><div><h3>本地优先与最小必要</h3><p>默认在本地环境处理影像，只处理完成当前分析所需的最少数据；正式接入真实数据前需完成授权、脱敏与访问控制。</p></div><em>LOCAL FIRST</em></div>
          <div className="privacy-card"><span>⌁</span><div><h3>版本记录与审计留痕</h3><p>记录数据来源、模型版本、参数、概率结果和人工复核状态，为异常追踪、性能监测和责任核验保留依据。</p></div><em>TRACEABLE</em></div>
        </div>

        <div className="medical-disclaimer reveal">
          <div className="disclaimer-mark"><span>LS</span><i /></div>
          <div><span className="mini-label">IMPORTANT CLINICAL DISCLAIMER</span><h3>本智能体结果仅供医师辅助诊疗分析</h3><p>本系统展示的分类概率、判别依据、文献与指南信息均不能替代影像科、病理科或临床专科医师的判断。若模型结果与患者症状、病理结果或医师判断不一致，应以完整临床证据和专业医师意见为准。任何真实临床使用均应在完成必要验证、伦理审查、数据合规和适用监管程序后开展。</p></div>
          <div className="boundary-flow"><span><i>01</i>数据授权</span><em>→</em><span><i>02</i>模型提示</span><em>→</em><span><i>03</i>医生复核</span><em>→</em><span><i>04</i>审计留痕</span></div>
        </div>

        <div className="release-showcase reveal" id="latest-release">
  <div className="release-showcase-heading"><span className="mini-label">NEW IN BETA.3 · 2026.11.17</span><h3>更清晰的工作台，更连贯的分析流程</h3><p>从影像导入到人工记录，把每一步的状态留在眼前。</p></div>
  <div className="release-feature-grid">
    <article><span>01 / REVIEW</span><h4>看得清，也记得住</h4><p>缩放与大图查看、Grad-CAM 叠加、人工标记和结构化报告，连接同一次分析。</p></article>
    <article><span>02 / CONTINUITY</span><h4>任务进度可以继续</h4><p>后台队列支持取消与继续、重启恢复；已完成项目保留，失败项有明确提示。</p></article>
    <article><span>03 / EXPERIENCE</span><h4>交互反馈更明确</h4><p>亮色、夜间与护眼外观，清晰的模型状态，以及标记、复核和设置的草稿保护。</p></article>
  </div>
  <figure className="release-screenshot"><a href="/release/beta3-workbench.jpg" target="_blank" rel="noreferrer" aria-label="查看 beta.3 工作台原始截图"><img src="/release/beta3-workbench.jpg" alt="LungSight beta.3 夜间影像工作台，展示本地模型状态、任务队列、影像查看与四分类研究排序" loading="lazy" width="2526" height="1319" /></a><figcaption>软件实际界面 · 公开示例与测试记录 · 图中数值为研究排序，不构成诊断。</figcaption></figure>
  <p className="release-service-note">可在设置页接入 DeepSeek、ChatGPT 或 Kimi（需自行配置服务商 API Key）。CT 像素保留本地；云端问答仅接收结构化上下文与检索摘录。</p>
  <div className="release-document-links"><a href="https://github.com/wxy11117/LungSight/releases/tag/v0.1.0-beta.3">查看更新说明 ↗</a><a href="https://github.com/wxy11117/LungSight/blob/main/documentation/COMPETITION_DEMO_GUIDE.md">演示与使用步骤 ↗</a><a href="https://github.com/wxy11117/LungSight/blob/main/documentation/MODEL_CARD_RESEARCH_2026-09-03.md">模型适用范围 ↗</a></div>
</div>
<div className="app-release-gateway reveal" id="app-download">
          <div className="app-release-brand"><MedicalBrandMark /><div><small>DESKTOP APPLICATION</small><h3>LungSight 桌面端</h3><p>新版影像工作台 · 后台任务恢复 · 三种外观与草稿保护</p></div></div>
          <div className="release-progress" aria-label="应用发布状态"><span className="done"><i>✓</i><b>网页原型</b><small>已完成</small></span><em>→</em><span className="done"><i>✓</i><b>模型服务</b><small>已集成</small></span><em>→</em><span className="done"><i>✓</i><b>工程流程验收</b><small>已通过</small></span><em>→</em><span className="active"><i>4</i><b>安装包发布</b><small>公共测试</small></span></div>
          <div className="release-action release-action-ready"><span><i /> RELEASE STATUS</span><strong>公共测试版</strong><a className="download-button" href="https://github.com/wxy11117/LungSight/releases/download/v0.1.0-beta.3/LungSight-Setup-0.1.0-beta.3-win-x64.exe" rel="noreferrer" aria-label="下载 LungSight 0.1.0 beta 3 Windows 64位安装包"><i>⇩</i><span>下载 Windows 安装包</span></a><small>v0.1.0-beta.3 · Windows 10/11 x64 · 约 668 MB<br /><a href="https://github.com/wxy11117/LungSight/releases/download/v0.1.0-beta.3/SHA256SUMS.txt" rel="noreferrer">下载 SHA256 校验文件 ↗</a></small></div>
        </div>

        <div className="responsibility-sources reveal"><span>设计参考</span><a href="https://www.who.int/publications/i/item/9789240029200" target="_blank" rel="noreferrer">WHO《人工智能促进健康的伦理与治理》↗</a><a href="https://xzfg.moj.gov.cn/mobile/law/detail?LawID=1739" target="_blank" rel="noreferrer">《医疗器械监督管理条例》↗</a><p>以上信息用于说明设计原则，不构成法律或合规意见；实际应用应根据部署地区、预期用途和最新规则进行专业评估。</p></div>
      </section>

      <footer className="creator-footer" id="creator">
        <div className="creator-footer-main">
          <div className="creator-brand">
            <span className="creator-caption"><i /> CREATOR BRAND</span>
            <img className="creator-logo-image" src="/qions-med-logo.png" alt="QIONS MED Medical Intelligence 创作者标识" />
            <p>以探索驱动技术创新，为 LungSight 肺影智析提供产品设计与软件创作支持。</p>
          </div>

          <nav className="footer-links" aria-label="页脚快速链接">
            <span>快速链接</span>
            <a href="#technology">核心技术 <i>↗</i></a>
            <a href="#workflow">工作流程 <i>↗</i></a>
            <a href="#tech-graph">技术生态 <i>↗</i></a>
            <a href="#responsibility">责任边界 <i>↗</i></a>
          </nav>

          <div className="creator-contact">
            <span>联系创作者</span>
            <a href="https://wpa.qq.com/msgrd?v=3&uin=2934935729&site=qq&menu=yes" target="_blank" rel="noreferrer"><i>QQ</i><b>2934935729</b><em>↗</em></a>
            <a href="mailto:2934935729@qq.com"><i>@</i><b>2934935729@qq.com</b><em>↗</em></a>
            <small>欢迎就项目合作、产品体验与技术交流取得联系</small>
          </div>
        </div>

        <div className="footer-bottom">
          <div className="footer-brand"><MedicalBrandMark /><div><b>LungSight 肺影智析</b><small>AI-ASSISTED LUNG CT ANALYSIS</small></div></div>
          <p>以算法为起点，让优质影像分析能力更可及。</p>
          <div><span>科研原型 · 非医疗器械</span><span>© 2026 QIONS · LungSight Team</span></div>
        </div>
      </footer>
    </main>
  );
}
