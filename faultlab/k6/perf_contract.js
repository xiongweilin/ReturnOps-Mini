// 性能契约：不是「能扛多少 QPS」，而是退化必须被证据抓到。
// 阈值来自 fault-lab 栈上的实测基线。最后一项比延迟更重要：
// 同一个 Idempotency-Key 的两次请求必须落到同一个案子。
import http from 'k6/http';
import { check } from 'k6';
import { Counter } from 'k6/metrics';

const baseUrl = __ENV.BASE_URL || 'http://127.0.0.1:8000';
const orgId = __ENV.ORG_ID || '';
const orgToken = __ENV.ORG_TOKEN || '';

const duplicateEffects = new Counter('duplicate_effect');
const createStatus = new Counter('create_status');
const replayStatus = new Counter('replay_status');

export const options = {
  scenarios: {
    read_write: {
      executor: 'constant-vus',
      vus: Number(__ENV.VUS || 10),
      duration: __ENV.DURATION || '20s',
    },
  },
  thresholds: {
    http_req_failed: ['rate<0.01'],
    http_req_duration: ['p(95)<500', 'p(99)<1000'],
    duplicate_effect: ['count==0'],
  },
};

export default function () {
  const health = http.get(baseUrl + '/health');
  check(health, { 'health is 200': (r) => r.status === 200 });

  const key = 'perf-' + __VU + '-' + __ITER;
  const headers = {
    'Content-Type': 'application/json',
    'Idempotency-Key': key,
    Authorization: 'Bearer ' + orgToken,
    'X-Organization-ID': orgId,
  };
  const body = JSON.stringify({
    external_order_ref: 'ORDER-' + __VU + '-' + __ITER,
    customer_ref: 'perf-contract',
    reason: 'performance contract',
    requested_amount_minor: 1000,
    currency: 'USD',
  });

  const first = http.post(baseUrl + '/v1/returns', body, { headers: headers });
  const replay = http.post(baseUrl + '/v1/returns', body, { headers: headers });

  const created = check(first, { 'create returns 201': (r) => r.status === 201 });
  createStatus.add(1, { code: String(first.status) });
  replayStatus.add(1, { code: String(replay.status) });
  if (!created || replay.status !== 201) {
    return;
  }

  const firstCase = JSON.parse(first.body).result.id;
  const replayCase = JSON.parse(replay.body).result.id;
  if (firstCase !== replayCase) {
    // 同一 Idempotency-Key 产生两个案子：比延迟严重得多的失败。
    duplicateEffects.add(1);
  }
}
