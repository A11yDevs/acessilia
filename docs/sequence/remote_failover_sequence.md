# Remote capability call with retries and failover

> A Brazilian Portuguese translation is available in [remote_failover_sequence.pt-br.md](remote_failover_sequence.pt-br.md).

Diagram: [remote_failover_sequence.puml](remote_failover_sequence.puml). This page describes it in text. The behaviour is in `libs/sdk/src/acessilia_sdk/toolbox/client.py`; the decisions are [ADR-0003](../adr/0003-remote-only-operational-capabilities.md) and [ADR-0006](../adr/0006-availability-and-failover.md).

1. **The core asks the SDK for a capability**, for example `math.convert`. The SDK client comes from `make_toolbox_client`, configured from the core's settings.
2. **Endpoint 1 is `TOOLBOX_BASE_URL`, normally a load balancer** in front of stateless Toolbox replicas that share MinIO and Valkey. Availability comes from those replicas. The SDK sends the request without checking the catalogue first.
3. **Retries happen on the same endpoint.** A timeout, a network error or a `503`/`504` is retried up to `TOOLBOX_RETRIES` times, waiting `TOOLBOX_RETRY_BACKOFF_SECONDS` × 2ⁿ with jitter between attempts.
4. **Any other error is raised at once:** a `4xx`, another `5xx` such as `500` or `502`, or a contract violation. The SDK treats it as an answer from a reachable Toolbox, which would be the same on every endpoint, so it is neither retried nor failed over.
5. **Endpoint 2 is optional.** It comes from `TOOLBOX_BASE_URLS`, which lists **independent** Toolbox deployments, and is tried only after endpoint 1 has failed. The SDK first reads that endpoint's catalogue (`/v1/capabilities` and `/v1/providers`, cached). If the capability, its contract version or the provider is not published there, the endpoint is skipped. Otherwise the same request is sent, with the same retries.
6. **On success, the result comes back with the HTTP client of the endpoint that served it.** An artifact the capability produced is downloaded and verified from that same endpoint.
7. **When every endpoint fails**, the SDK raises the single failure, or `ToolboxUnavailable` listing every cause when two or more endpoints failed. There is **no local fallback**: the core decides what the failure means.
   - Structure extraction fails the job, with an explicit message.
   - PDF/UA and DOCX become optional export errors; the other formats are still delivered.
   - Math enrichment and media inspection degrade with a recorded warning, and a failed PDDL method can be replanned.
