const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function createElement(id) {
  return {
    id,
    innerHTML: '',
    textContent: '',
    style: {},
    dataset: {},
    disabled: false,
    files: [],
    classList: {
      values: new Set(['hidden']),
      add(...names) {
        names.forEach(name => this.values.add(name));
      },
      remove(...names) {
        names.forEach(name => this.values.delete(name));
      },
      contains(name) {
        return this.values.has(name);
      }
    },
    addEventListener() {},
    scrollIntoView() {}
  };
}

function createDocument() {
  const elements = new Map();
  const ids = [
    'langToggle',
    'fileNameDisplay',
    'contractFile',
    'startAnalysisBtn',
    'overview-section',
    'explanation-section',
    'cases-section',
    'riskLevelCard',
    'riskOverviewCard',
    'learningGuideCard',
    'riskBreakdownList',
    'relatedScamCard',
    'protectCard',
    'learningPathCard'
  ];

  ids.forEach(id => elements.set(id, createElement(id)));

  const apiHint = createElement('api-hint');
  apiHint.classList.values = new Set();

  return {
    body: { dataset: { page: 'home' } },
    documentElement: { lang: 'en' },
    getElementById(id) {
      return elements.get(id) || null;
    },
    querySelector(selector) {
      if (selector === '.api-hint') return apiHint;
      if (selector === '#learningGuideCard [data-scroll-target]') return createElement('guide-link');
      return null;
    },
    querySelectorAll() {
      return [];
    },
    addEventListener() {}
  };
}

function loadApp() {
  const document = createDocument();
  const context = {
    window: {
      GPTSCAN_CONFIG: {},
      location: { protocol: 'http:' }
    },
    document,
    localStorage: {
      getItem() { return 'en'; },
      setItem() {}
    },
    Chart: function Chart() {},
    FormData: class FormData {
      append() {}
    },
    fetch: async () => ({ ok: true, json: async () => ({}) }),
    setInterval: () => 1,
    clearInterval() {},
    setTimeout,
    clearTimeout,
    console
  };
  context.window.document = document;
  context.window.localStorage = context.localStorage;
  context.window.Chart = context.Chart;
  context.window.fetch = context.fetch;
  context.window.setInterval = context.setInterval;
  context.window.clearInterval = context.clearInterval;

  const source = fs.readFileSync(path.join(__dirname, '..', 'code_sandbox_light_f9139025_1775118386', 'js', 'app.js'), 'utf8');
  const instrumented = `${source}
window.__testHooks = {
  renderScanResult,
  resetScanResultSections,
  getLatestScanResponse: () => latestScanResponse,
  setLatestScanResponse: value => { latestScanResponse = value; }
};`;
  vm.runInNewContext(instrumented, context, { filename: 'app.js' });
  return { context, document };
}

function assert(condition, message) {
  if (!condition) {
    throw new Error(message);
  }
}

function testResetClearsRenderedResult() {
  const { context, document } = loadApp();
  const hooks = context.window.__testHooks;
  hooks.renderScanResult({
    status: 'success',
    uploadedFile: { name: '6.zip' },
    result: {
      summary: { status: 'success', statusLabel: 'Scan Completed', usedTimeSeconds: 10, resultCount: 1 },
      project: { name: 'project', detectedPragma: '0.7.6', solcVersion: '0.7.6' },
      findings: [{ severity: 'high', displayTitle: 'Issue', description: 'desc', recommendation: 'fix', primaryLocation: { label: 'A.sol:1-2' } }]
    },
    metadata: {}
  });

  assert(!document.getElementById('overview-section').classList.contains('hidden'), 'overview should be visible after rendering');

  hooks.resetScanResultSections();

  assert(document.getElementById('overview-section').classList.contains('hidden'), 'overview should be hidden after reset');
  assert(document.getElementById('explanation-section').classList.contains('hidden'), 'explanation should be hidden after reset');
  assert(document.getElementById('cases-section').classList.contains('hidden'), 'cases should be hidden after reset');
  assert(document.getElementById('riskOverviewCard').innerHTML === '', 'risk overview card should be cleared');
  assert(hooks.getLatestScanResponse() === null, 'latest scan response should be cleared');
}

function testResultsSectionIsPlacedBelowInputSection() {
  const html = fs.readFileSync(
    path.join(__dirname, '..', 'code_sandbox_light_f9139025_1775118386', 'index.html'),
    'utf8'
  );
  const inputIndex = html.indexOf('id="input-section"');
  const overviewIndex = html.indexOf('id="overview-section"');
  const statsIndex = html.indexOf('id="stats-section"');

  assert(inputIndex !== -1, 'input section should exist');
  assert(overviewIndex !== -1, 'overview section should exist');
  assert(statsIndex !== -1, 'stats section should exist');
  assert(inputIndex < overviewIndex, 'overview section should be below input section');
  assert(overviewIndex < statsIndex, 'stats section should come after result sections');
}

try {
  testResetClearsRenderedResult();
  testResultsSectionIsPlacedBelowInputSection();
  process.stdout.write('ok\n');
} catch (error) {
  process.stderr.write(`${error.message}\n`);
  process.exit(1);
}
