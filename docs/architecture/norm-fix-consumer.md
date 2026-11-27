# Remote normalization consumer (#929)

Brazilian Portuguese: [português brasileiro](norm-fix-consumer.pt-br.md).

Core 0.3.30 uses SDK 0.7.1 to execute `norm-fix` through
`document.text.normalize@1`, with `docstruct-text@1.0.0` and Docstruct 0.5.8.
The provider, dependency guard and operation-identity prerequisite shipped in
[Toolbox #174](https://github.com/A11yDevs/acessilia-toolbox/pull/174) and
[#177](https://github.com/A11yDevs/acessilia-toolbox/pull/177). Public schemas and
catalogue were captured byte-for-byte at Toolbox
`b1ac9178c15e394860d4ee1adb9cc694a4602db3`; the SDK models are generated from
those files. This follows accepted [ADR-0032](../adr/0032-toolbox-runtime-library-placement.md).

## Ownership and compatibility

The Core selects the existing obligation's targets in reading order, decides
acceptance and updates its metadata. The SDK snapshots/encodes bounded DTOs,
uses the public authenticated executor transport and validates observations.
Only the Toolbox invokes the normalization algorithm. `text.postprocess@1`
remains a separate contract with different marker/deduplication semantics.

Empty/null targets remain unchanged and require no request. Missing targets,
no-text failure, nonempty processed counts, one-pass output and `norm_fixed=true`
only on changed targets match the original handler. Other metadata is preserved.
The handler contains no local algorithm fallback. Its pinned computational import
and `LOCAL_METHODS` entry are removed; the existing detector and legacy fusion
wrapper imports remain explicitly inventoried migration debt.

`TOOLBOX_TEXT_NORMALIZE_PROVIDER` defaults to `docstruct-text` and enters the
processing/checkpoint identity. The availability gate requires the versioned
capability and selected provider binding. Runtime responses must additionally
prove provider 1.0.0 / Docstruct and `norm_fix` 0.5.8. An absent/older capability,
remote failure or incompatible runtime fails explicitly, without local repair.
The existing SDK classification of capability HTTP 404 as an artifact error is
tracked separately in [#949](https://github.com/A11yDevs/acessilia/issues/949);
the handler still refuses the result and preserves the original input.
Transport budgets, cache policy and authorized endpoint failover use the run's
existing Toolbox configuration. No new queue, image or service is required.

The shipped PDDL domain/description remain frozen so saved-plan hashes stay
valid. Existing obligation granularity is preserved: the default detector
currently emits one normalization obligation per affected element. A multi-target
obligation uses bounded batches; independent obligations are not merged or
prefetched. [#948](https://github.com/A11yDevs/acessilia/issues/948) evaluates that
remaining planning/performance decision and removal of local prediction.

## Binding, atomic acceptance and recovery

- Each request has at most 256 unique ids (1–256 characters) and **1,048,576
  serialized UTF-8 bytes**, including envelope, separators and escaping.
  Oversized indivisible text/ids are refused, never truncated or split across
  algorithm boundaries. All batches are prepared before any RPC.
- The consumer checks the actual response key `document.text.normalize@1`,
  provenance capability/version/provider, component versions, complete payload
  fingerprint and empty-parameter fingerprint. Per-target fingerprints use the
  original canonical UTF-8 `{"id":id,"text":text}`; shared vectors were captured
  from the provider. IDs/order, types, counts, flags, UTF-8 and null/empty
  preservation are checked before applying observations. A fingerprint alone
  does not establish output correctness; Core does not recompute the algorithm.
- No target is changed until every batch validates and the current source,
  manifest revision, obligation and target snapshots still match. A later-batch
  failure or stale context leaves the obligation's text/metadata untouched.
  Memory scales with the obligation's snapshots/observations; the per-request
  ceiling is not a whole-obligation or HTTP-response memory ceiling.
- Core creates a separate operation slot from semantic context, selected
  contract/provider/component versions, cache policy and the immutable batch.
  The existing job operation journal supplies stable ids across retries/restart
  and the existing registry makes active batches cancellable. Attempt ids change
  per HTTP attempt. Without a hosting job port, ids are fresh per invocation.
- An interrupted multi-batch obligation has no applied prefix to checkpoint:
  rehydration retries the original batches. A retained Toolbox outcome may join;
  eviction/restart/independent replicas can execute that pure input again.
  Once the executor commits a whole step, its existing checkpoint preserves
  text, metadata and obligation state together; resume skips it. It never feeds
  a returned one-pass result back as the original retry input.
- Cooperative cancellation and publication retain the existing ADR-0019 limits;
  acknowledgement is not preemption or rollback of started storage/cache writes.
  Inline observations use the existing remote storage/cache/retention policy.

## Evidence and local qualification

Frozen original-handler observations cover mixed, empty and protected/no-op
targets. Adversarial consumer tests cover byte/count/Unicode boundaries,
malformed/stale identities, flags/counts, later-batch failure and journal reuse.
The differential harness adds `text-normalization` and serves the real versioned
envelope. All five historical references were re-recorded from their original
commits; the 40 pre-existing canonical documents remain identical. The new case
matches the historical local path. A file-checkpoint resume preserves a committed
non-fixed-point result (`a-\nb-\nc` becomes `ab-\nc`) while completing the next step.

The [qualification tool](../../scripts/bench/text_normalization.py) loads the
unchanged original handler from Core `add11c46db9ab8e28eaeb54b4319c3fcf6509392`.
It compares text, metadata and method outcomes through actual loopback HTTP to
the merged Toolbox in a separate Python environment, with filesystem storage
and Redis. A 257-target interruption/restart uses the real SQLite operation
journal and file checkpoints: the first response joins identically with the
execution cache disabled. Test services are temporary and were stopped.

Three local runs, with an explicit synthetic **5 ms delay per request**, produced
the following [raw measurements](norm-fix-consumer-measurements.json):

| 64-target mode | Total requests | Median handler latency per run (ms) | Total request-body bytes | Total response-body bytes |
|---|---:|---:|---:|---:|
| Original local handler | 0 | 2.276 | 0 | 0 |
| Individual remote invocations | 192 | 5,917.067 | 101,124 | 274,500 |
| One obligation, bounded batch | 3 | 84.257 | 9,648 | 35,616 |
| Warm remote cache | 3 | 73.006 | 9,369 | 35,613 |

Four concurrent batch invocations (12 runs total) used 12 requests, with a median
204.142 ms; they retained the same observations. A **1,047,581-byte JSON input**
used one request per run: local median 183.858 ms, uncached remote 390.990 ms,
warm-cache remote 178.113 ms. Warm phases confirmed three cache hits each.

Raw evidence also records qualification-process CPU (including fixture/oracle
checks and HTTP capture), process-lifetime parent peak RSS, sampled server CPU/RSS
and storage growth (134 files / 966,668 bytes, including metadata, over the
existing four-file baseline). Parent CPU/RSS are not isolated production Core
measurements; sampled server RSS is not its peak. Wire instrumentation and local
storage/cache affect timings. Three runs and synthetic loopback delay do not
establish production latency, MinIO/Valkey behavior, throughput or quality gains.
Individual mode includes repeated handler/client setup. The batch comparison
uses one multi-target obligation, not a claim that default per-element plans
already coalesce. Remote execution remains more expensive than the local oracle
in the uncached samples; the purpose is execution ownership and bounded transport.

To reproduce, start an isolated Toolbox at the recorded source ref with the
`api,storage,cache` extras, a filesystem artifact provider and temporary Redis,
then run from the Core checkout:

```bash
uv run python -m scripts.bench.text_normalization \
  --base-url http://127.0.0.1:8002 --api-key normalization-benchmark \
  --legacy-ref add11c46db9ab8e28eaeb54b4319c3fcf6509392 \
  --server-pid <toolbox-pid> --storage-root <temporary-artifact-root> \
  --iterations 3 --delay-ms 5 --out /tmp/norm-qualification.json
```
