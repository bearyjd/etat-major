---
id: 0031
project: netlens
title: Live latency graph
problem: Users cannot see latency trends during a scan.
outcome: A graph of round-trip time per host over the last 5 minutes.
status: planned
priority: 2
research: [research:0007]
decisions: [decision:0012]
acceptance:
  - id: a1
    text: Graph updates at least once per second.
  - id: a2
    text: Graph is covered by an automated test.
architecture:
  - ref: fp:n:ui.hostdetail
    relation: modifies
  - ref: fp:f:app/src/net/Latency.kt
    relation: new
---
