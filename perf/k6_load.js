// k6 load / stress / spike harness for the Aria AI Front Desk API (GAP-PERF / H-7).
//
// This is NOT part of the pytest suite — it drives real HTTP load against a
// deployed (ideally staging) instance. Install k6 (https://k6.io) then run:
//
//   BASE_URL=https://aifrontdesk.taborsynergy.com SLUG=demo k6 run perf/k6_load.js
//
// Scenarios (pick one with --env STAGE=load|stress|spike|soak):
//   load   - 50 VUs ramp, steady   (baseline capacity)
//   stress - ramp to 500 VUs       (find the knee / graceful 429s, not 500s)
//   spike  - 0 -> 200 in 10s        (cold-start / autoscale behaviour)
//   soak   - 50 VUs for 2h          (memory leak / endurance)
import http from "k6/http";
import { check, sleep } from "k6";

const BASE = __ENV.BASE_URL || "http://localhost:8000";
const SLUG = __ENV.SLUG || "demo";
const STAGE = __ENV.STAGE || "load";

const SCENARIOS = {
  load:   { executor: "ramping-vus", startVUs: 0, stages: [
            { duration: "30s", target: 50 }, { duration: "2m", target: 50 }, { duration: "30s", target: 0 } ] },
  stress: { executor: "ramping-vus", startVUs: 0, stages: [
            { duration: "1m", target: 100 }, { duration: "2m", target: 500 }, { duration: "1m", target: 0 } ] },
  spike:  { executor: "ramping-vus", startVUs: 0, stages: [
            { duration: "10s", target: 200 }, { duration: "1m", target: 200 }, { duration: "20s", target: 0 } ] },
  soak:   { executor: "constant-vus", vus: 50, duration: "2h" },
};

export const options = {
  scenarios: { main: SCENARIOS[STAGE] },
  thresholds: {
    http_req_failed:   ["rate<0.01"],            // <1% errors
    http_req_duration: ["p(95)<3000"],           // p95 under 3s
  },
};

export default function () {
  // Health (cheap) + a real chat turn (LLM path) to exercise the hot path.
  const health = http.get(`${BASE}/api/health`);
  check(health, { "health 200": (r) => r.status === 200 });

  const chat = http.post(`${BASE}/api/${SLUG}/chat`,
    JSON.stringify({ message: "What are your office hours?" }),
    { headers: { "Content-Type": "application/json" } });
  check(chat, {
    "chat ok or rate-limited": (r) => r.status === 200 || r.status === 429,
    "chat not 5xx": (r) => r.status < 500,
  });

  sleep(1);
}
