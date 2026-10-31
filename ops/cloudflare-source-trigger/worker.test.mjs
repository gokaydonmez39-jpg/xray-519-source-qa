import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const cfg=JSON.parse(fs.readFileSync(new URL('./wrangler.jsonc',import.meta.url),'utf8'));
test('UTC :01 cron and SQLite lock on Free-compatible configuration',()=>{
  assert.deepEqual(cfg.triggers.crons,['1 * * * *']);
  assert.equal(cfg.durable_objects.bindings[0].class_name,'SourceDispatchLock');
  assert.equal(cfg.exports.SourceDispatchLock.storage,'sqlite');
  assert.equal(cfg.workers_dev,false);
  assert.ok(!JSON.stringify(cfg).includes('TOKEN'));
});
test('Worker has no HTTP public dispatch route, private strategy or order path',()=>{
  const src=fs.readFileSync(new URL('./worker.mjs',import.meta.url),'utf8');
  assert.match(src,/fetch\(\) \{ return new Response\('Not found', \{ status: 404 \}\)/);
  assert.match(src,/INSERT OR IGNORE INTO dispatch_epoch/);
  assert.match(src,/redirect: 'error'/);
  assert.doesNotMatch(src,/api\/v3\/order|xray-crypto-godzilla-omega/);
});
