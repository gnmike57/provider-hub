// Throwaway probe: replicates the CLI's loadConfig() path for .ts files
// (createJiti(__filename, { moduleCache:false, interopDefault:true }) +
// jiti.import(path, { default:true })) against agent-tars.config.ts.
const { createJiti } = require('jiti');
const path = require('path');

const jiti = createJiti(__filename, { moduleCache: false, interopDefault: true });
const configPath = path.resolve(__dirname, 'agent-tars.config.ts');

jiti
  .import(configPath, { default: true })
  .then((cfg) => {
    console.log('LOADED OK via jiti (CLI loader path)');
    console.log('model.provider :', cfg.model.provider);
    console.log('model.id       :', cfg.model.id);
    console.log('model.baseURL  :', cfg.model.baseURL);
    console.log('model.apiKey   :', cfg.model.apiKey ? cfg.model.apiKey.slice(0, 8) + '...' : 'MISSING');
    console.log('browser.control:', cfg.browser.control);
    console.log('browser.headless:', cfg.browser.headless);
    console.log('planner.enable :', cfg.planner.enable);
    console.log('workspace      :', cfg.workspace);
  })
  .catch((e) => {
    console.error('LOAD FAILED:', e.message);
    process.exit(1);
  });
