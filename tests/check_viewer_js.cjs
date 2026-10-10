const vm = require('node:vm');
const assert = require('node:assert/strict');

(async () => {
  const html = await (await fetch('http://127.0.0.1:8768/book/test-book')).text();
  const scripts = [...html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)]
    .filter(match => !match[0].includes('application/json'));
  for (const [, code] of scripts) new vm.Script(code);
  const code = scripts.find(match => match[1].includes('function unlockRegistration'))[1];
  const callback = code.slice(code.indexOf('function unlockRegistration'), code.indexOf('function mountRegistrationForm'));
  const nodes = [];
  const mount = {replaceChildren() {}, append(...children) {nodes.push(...children);}};
  const context = {
    manifest: {slug:'test-book', title:'Test Book'}, registrationAccessKey:'test',
    sessionStorage: {setItem() {}}, renderReader() {},
    document: {
      getElementById() {return mount;}, querySelector() {return {};},
      createTextNode(text) {return {textContent:text};},
      createElement(tag) {return {tag, setAttribute() {}, addEventListener() {}};}
    }
  };
  vm.runInNewContext(callback + ';unlockRegistration()', context);
  assert(nodes.some(n => n.textContent === 'Thank you!'));
  assert(nodes.some(n => n.href === '/api/publications/test-book/original.pdf'));
  assert(nodes.some(n => n.textContent === 'Read Flipbook'));
  console.log('Viewer JavaScript parses; successful-submit callback shows title-specific download and read actions.');
})().catch(error => {console.error(error); process.exitCode = 1;});
