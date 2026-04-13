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
    classList: {
      values: new Set(),
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
  [
    'langToggle',
    'resourceGrid',
    'resourceDetailPanel',
    'knowledgeGrid',
    'knowledgeDetailPanel',
    'policyList',
    'policyDetailPanel'
  ].forEach(id => elements.set(id, createElement(id)));

  return {
    body: { dataset: { page: 'education' } },
    documentElement: { lang: 'en' },
    getElementById(id) {
      return elements.get(id) || null;
    },
    querySelector() {
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
      getItem() { return 'zh'; },
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

  const source = fs.readFileSync(path.join(__dirname, '..', 'code_sandbox_light_f9139025_1775118386', 'js', 'app.js'), 'utf8');
  const instrumented = `${source}
window.__educationHooks = { renderEducationHub, toggleEducationAccordion };`;
  vm.runInNewContext(instrumented, context, { filename: 'app.js' });
  return { context, document };
}

function assert(condition, message) {
  if (!condition) {
    throw new Error(message);
  }
}

function countOccurrences(text, pattern) {
  const matches = text.match(new RegExp(pattern, 'g'));
  return matches ? matches.length : 0;
}

function testEducationHubRendersStructuredInteractiveContent() {
  const { context, document } = loadApp();
  context.window.__educationHooks.renderEducationHub();

  const resourceHtml = document.getElementById('resourceGrid').innerHTML;
  const knowledgeHtml = document.getElementById('knowledgeGrid').innerHTML;
  const policyHtml = document.getElementById('policyList').innerHTML;
  const resourceDetailHtml = document.getElementById('resourceDetailPanel').innerHTML;
  const knowledgeDetailHtml = document.getElementById('knowledgeDetailPanel').innerHTML;
  const policyDetailHtml = document.getElementById('policyDetailPanel').innerHTML;

  assert(resourceHtml.includes('學生專區'), 'student resource card should render');
  assert(resourceHtml.includes('教育者專區'), 'educator resource card should render');
  assert(resourceHtml.includes('市民專區'), 'citizen resource card should render');
  assert(resourceHtml.includes('查看內容'), 'resource cards should expose a view-details button');
  assert(resourceHtml.includes('普通市民在轉出資產或授權錢包前'), 'resource cards should include user-facing civic education copy');
  assert(!resourceHtml.includes('下載課程包'), 'resource cards should not show download-oriented actions');
  assert(resourceDetailHtml === '', 'resource detail panel should start empty');

  assert(countOccurrences(knowledgeHtml, 'accordion-card') === 6, 'knowledge base should render six accordion items');
  assert(knowledgeHtml.includes('icon-toggle-btn'), 'knowledge items should expose a dedicated plus button');
  assert(knowledgeHtml.includes('無限制增發權限'), 'knowledge titles should be localized for users');
  assert(knowledgeDetailHtml === '', 'knowledge detail panel should start empty');

  assert(countOccurrences(policyHtml, 'policy-item policy-accordion') === 3, 'policy guide should render three expandable items');
  assert(policyHtml.includes('查看詳情'), 'policy cards should expose a visible details control');
  assert(policyDetailHtml === '', 'policy detail panel should start empty');
}

function testEducationAccordionOpensOneItemPerSection() {
  const { context, document } = loadApp();
  const hooks = context.window.__educationHooks;

  hooks.renderEducationHub();
  assert(!document.getElementById('knowledgeGrid').innerHTML.includes('aria-expanded="true"'), 'knowledge items should start collapsed');
  assert(document.getElementById('knowledgeDetailPanel').innerHTML === '', 'knowledge detail panel should be empty before interaction');

  hooks.toggleEducationAccordion('knowledge', 0);
  let knowledgeHtml = document.getElementById('knowledgeGrid').innerHTML;
  assert(countOccurrences(knowledgeHtml, 'aria-expanded="true"') === 1, 'opening one knowledge item should expand only one item');
  let knowledgeDetailHtml = document.getElementById('knowledgeDetailPanel').innerHTML;
  assert(knowledgeDetailHtml.includes('這是什麼'), 'opening one knowledge item should render detail content into the shared panel');
  assert(knowledgeDetailHtml.includes('無限制增發權限') === false, 'knowledge detail panel should focus on explanation blocks, not duplicate title text');

  hooks.toggleEducationAccordion('knowledge', 2);
  knowledgeHtml = document.getElementById('knowledgeGrid').innerHTML;
  assert(countOccurrences(knowledgeHtml, 'aria-expanded="true"') === 1, 'switching knowledge items should keep only one expanded');
  assert(knowledgeHtml.includes('暫停或凍結功能'), 'selected knowledge item should be present after switching');
  knowledgeDetailHtml = document.getElementById('knowledgeDetailPanel').innerHTML;
  assert(knowledgeDetailHtml.includes('誰可啟動、在什麼條件下啟動'), 'switching items should replace the shared detail content');

  hooks.toggleEducationAccordion('policy', 1);
  const policyHtml = document.getElementById('policyList').innerHTML;
  const policyDetailHtml = document.getElementById('policyDetailPanel').innerHTML;
  assert(countOccurrences(policyHtml, 'aria-expanded="true"') === 1, 'policy section should also keep only one expanded item');
  assert(policyDetailHtml.includes('官方連結'), 'policy detail panel should include official links');
  assert(policyDetailHtml.includes('ifec.org.hk'), 'policy detail panel should render official IFEC links');

  hooks.toggleEducationAccordion('resources', 2);
  const resourceHtml = document.getElementById('resourceGrid').innerHTML;
  const resourceDetailHtml = document.getElementById('resourceDetailPanel').innerHTML;
  assert(countOccurrences(resourceHtml, 'aria-expanded="true"') === 1, 'resource section should also keep only one expanded item');
  assert(resourceDetailHtml.includes('你現在應該怎樣做'), 'resource detail panel should render action-oriented guidance');
  assert(resourceDetailHtml.includes('建議做法'), 'resource detail panel should render suggested actions');
  assert(resourceDetailHtml.includes('不要因為專案很紅'), 'resource detail panel should include user-facing action steps');
}

try {
  testEducationHubRendersStructuredInteractiveContent();
  testEducationAccordionOpensOneItemPerSection();
  process.stdout.write('ok\n');
} catch (error) {
  process.stderr.write(`${error.message}\n`);
  process.exit(1);
}
