import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const page = readFileSync(new URL('../app/analysis/page.tsx', import.meta.url), 'utf8');
const styles = readFileSync(new URL('../app/globals.css', import.meta.url), 'utf8');

test('multiple CT images use the case-series endpoint and render aggregate evidence', () => {
  assert.match(page, /\/api\/analyze\/series/);
  assert.match(page, /form\.append\('files', file\)/);
  assert.match(page, /病例综合结果/);
  assert.match(page, /切片一致率/);
  assert.match(page, /生成聚合输出与局限说明/);
  assert.match(page, /prediction\.decision === 'INDETERMINATE'/);
});

test('case upload includes privacy guidance and readable series states', () => {
  assert.match(page, /请勿填写患者身份信息/);
  assert.match(page, /病例级结论已阻断/);
  assert.match(styles, /\.analysis-series\.indeterminate/);
  assert.match(styles, /\.analysis-case-name input/);
});

test('saved cases can be reopened, inspected and exported', () => {
  assert.match(page, /\/api\/series\?limit=20/);
  assert.match(page, /openStoredSeries/);
  assert.match(page, /病例分析记录/);
  assert.match(page, /viewMode === 'attention'/);
  assert.match(page, /原始切片/);
  assert.match(page, /下载病例报告/);
  assert.match(page, /\/report/);
  assert.match(styles, /\.analysis-history/);
  assert.match(styles, /\.analysis-view-controls/);
});

test('DICOM series import is explicit, local and privacy gated', () => {
  assert.match(page, /DICOM序列/);
  assert.match(page, /\/api\/analyze\/dicom-series/);
  assert.match(page, /privacy_acknowledged/);
  assert.match(page, /原始DICOM或身份字段值/);
  assert.match(page, /像素隐私仍需人工复核/);
  assert.match(page, /派生切片/);
  assert.match(page, /肺野区间/);
  assert.match(page, /排除边缘低覆盖/);
  assert.match(page, /不是肺分割或病灶定位/);
  assert.match(styles, /\.analysis-dicom-consent/);
  assert.match(styles, /\.analysis-dicom-summary/);
});

test('case quality gate exposes research scores but blocks unsafe case conclusions', () => {
  assert.match(page, /适用性门控已阻断病例级结论/);
  assert.match(page, /内部最高排序/);
  assert.match(page, /病例级结论已阻断 · 内部最高排序/);
  assert.match(page, /quality_warning_ratio/);
  assert.match(styles, /\.analysis-quality-gate\.blocked/);
});

test('single-image result is labelled as research ranking rather than diagnosis', () => {
  assert.match(page, /内部最高排序（非诊断）/);
  assert.match(page, /达到内部研究门槛/);
  assert.match(page, /癌细胞形态识别/);
  assert.match(page, /权重为审计后重新训练/);
});
