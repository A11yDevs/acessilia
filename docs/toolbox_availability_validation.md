# Validating the Toolbox availability gate before enabling `enforce` (#809)

You can also read this documentation in **Brazilian Portuguese**: [português brasileiro](toolbox_availability_validation.pt-br.md)

- **Purpose:** let a maintainer reproduce the production evidence that #809
  requires before `enforce` becomes the normal behaviour.
- **Owner:** the maintainer or an authorised operator with access to the
  production logs and metadata. The developer of the change does not need to
  invent evidence or access systems without permission.
- **Scope:** jobs run since domain 2.4 (#781) was deployed, while the gate was
  in `observe`. Do not expose API keys, source documents or personal data.

## 1. What to collect

For each production job in the window:

1. **The gate log line.** Before #933, every decision with a blocked method
   produced:
   `Toolbox gate observing (catalogue <revision>): would remove — <method>: <reasons>`.
   After #933 the line is
   `Toolbox gate (catalogue <revision>): methods the catalogue rules out — ...`.
   Keep the revision and the reason for each method.
2. **`canonical_metadata.pddl_toolbox_availability`.** The fields that matter:
   - `mode`, `catalog_revision`, `catalog_error`;
   - `requirements`: the `(capability@version, provider)` pairs each method
     asked for;
   - `offered` and `offered_source`: what the snapshot published;
   - `blocked_methods`: what the gate would remove, with reasons;
   - `assumed_runnable_methods`: methods the plan used while the facts were
     assumed (`observe`);
   - `optional` and `degraded_methods`: optional calls the snapshot lacked.
3. **The endpoints in use.** `TOOLBOX_BASE_URL`, `TOOLBOX_BASE_URLS` and the
   provider settings, without the API key. Record whether the deployment uses
   one endpoint (normally the load balancer) or independent secondary
   deployments.
4. **The period and volume.** Start/end timestamps, number of jobs evaluated
   and number of jobs with at least one blocked method. An empty result is not
   evidence unless the number of evaluated jobs is recorded too.

## 2. Reproducible checks

Use the existing log aggregation, `jq`, or a small read-only script. The
following are examples; adapt the paths and field names to the deployment.

```bash
# 1. Historical observe decisions (before #933).
rg -N "Toolbox gate observing .*would remove" <logs> > /tmp/gate-observe.txt
wc -l /tmp/gate-observe.txt

# 2. New report lines (after #933).
rg -N "Toolbox gate .*methods the catalogue rules out" <logs> > /tmp/gate-enforce.txt
wc -l /tmp/gate-enforce.txt

# 3. Catalogue errors in the same window.
rg -N "catalog_error|Toolbox gate .*unavailable" <logs> | wc -l
```

For the canonical metadata, extract one record per job:

```bash
jq -r '
  .canonical_metadata.pddl_toolbox_availability
  | [.mode, .catalog_revision, .catalog_error,
     (.blocked_methods | keys | join(",")),
     (.assumed_runnable_methods | join(","))]
  | @tsv
' <canonical-documents>/*.json
```

## 3. Classify each blocked method

For every method in `blocked_methods` and every entry of
`assumed_runnable_methods`, answer:

| Question | Real gap | False positive |
|---|---|---|
| Does the capability exist in the catalogue at the contract version the SDK calls? | Missing version/capability | Present; the check is comparing the wrong id/version |
| Does the configured provider implement it? | Provider absent or incompatible | Provider registered under another setting/default |
| Is the check reading the deployment the client calls? | Primary is the intended deployment | Primary/secondary mismatch, wrong base URL, wrong key |
| Could the method actually run? | No | Yes, so the gate is over-restrictive |

Record the cause (`missing capability`, `missing provider`, `wrong version`,
`endpoint mismatch`, `catalogue read failure`, `false positive`) and the
method. Do not mark a missing requirement as offered to make the logs green.

## 4. Catalogue errors and staleness

- Count `catalog_error` by type (`ToolboxTimeout`, `ToolboxProviderUnavailable`,
  contract violation, bad URL).
- Check whether the decision used a snapshot inside
  `TOOLBOX_CATALOG_STALE_SECONDS` or fell back to fail-closed.
- Correlate errors with the deployment/replica period, not only with the
  document. A catalogue read failure is a Toolbox availability problem, not a
  document problem.
- Confirm which endpoint the gate read. The gate reads only the primary; see
  the limitation documented in `toolbox_integration.md` and
  [#938](https://github.com/A11yDevs/acessilia/issues/938).

## 5. Decision record

Add to #809 or the PR:

- [ ] Window analysed and number of jobs evaluated.
- [ ] Number of decisions with blocked methods.
- [ ] Each blocked method classified as a real gap or false positive.
- [ ] Analysis of `assumed_runnable_methods`.
- [ ] Frequency and causes of `catalog_error`, including the stale window.
- [ ] Versions/providers actually published and endpoints used.
- [ ] Explicit conclusion: is fail-closed safe for this deployment?

If there are relevant false positives, fix the check and repeat the window.
If the historical logs are insufficient, the maintainer must explicitly
approve an alternative protocol (for example a controlled staging comparison)
before production deployment; this document does not replace that decision.

## 6. Alternative when historical logs are insufficient

1. Use a staging environment with representative versions, providers and
   catalogue.
2. Compare the previous `observe` behaviour with the candidate `enforce`
   behaviour on equivalent documents.
3. Confirm that removed methods are really unavailable and that plans keep
   critical goals, admissible alternatives and degradation warnings.
4. Simulate a complete catalogue, a missing requirement, an incompatible
   version/provider, a catalogue failure/expiration and, when applicable,
   multi-endpoint failover.
5. Record the results, representativeness limits and approval criteria.
6. Define a controlled deployment and rollback before enabling `enforce` in
   production.

Staging is not automatically production evidence; replacing the original #809
criterion is a maintainer decision.
