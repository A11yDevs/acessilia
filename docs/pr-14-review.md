# Technical Review Report — PR #14

You can also read this documentation in **Brazilian Portuguese**: [português brasileiro](pr-14-review.pt-br.md)

## Context
This report consolidates the technical review of PR #14, which introduces a standalone REST API architecture in which the Web and Telegram clients consume processing over HTTP.

## Review scope
- Validation of functional risks (bugs and behavior regressions)
- Consistency analysis between API contracts and their implementation
- Verification of test coverage for critical scenarios

## Executive summary
The PR's architectural proposal is positive and follows a consistent direction that separates the processing core from the client interfaces.

However, two relevant findings were identified:
- 1 high-severity finding (blocks merging)
- 1 medium-severity finding (must be fixed in the same PR)

## Findings

### 1) High — Canceling a queued task does not prevent real execution
**Severity:** High  
**Type:** Functional regression / API contract break  
**Recommended status:** Block merging until fixed

**Description**
When a task is still in the queue and the user requests cancellation, the status is marked as cancelled in the state exposed by the API. However, the corresponding entry is not removed from the effective execution queue.

As a result, when the worker consumes the queue the task may be processed normally, including export and possible delivery of the result.

**Impact**
- The user receives a cancellation response, but processing may continue
- Unnecessary compute and operations cost
- Inconsistency between the cancel endpoint's contract and the actual behavior

**Likely cause**
- Cancellation changes only the observed state without removing the pending item in the queue structure
- Missing additional guard at the start of execution to abort a previously cancelled task

**Technical recommendation**
- Implement removal by task_id in the unified queue
- In the cancel endpoint, attempt removal from the queue before responding with success
- Add a defensive check at the start of the worker's execution to stop cancelled tasks before processing

---

### 2) Medium — Redundant file open in the HTTP client
**Severity:** Medium  
**Type:** Resource defect / stability  
**Recommended status:** Fix in the same PR

**Description**
In the file upload to the API, the file handle is opened redundantly. One handle is created and overwritten by another within the upload context.

**Impact**
- Risk of a file descriptor leak under sustained load
- Can escalate into an operational error from hitting the open-file limit

**Technical recommendation**
- Keep a single file open within the context block
- Build the multipart payload only with the context-managed handle

## Test coverage — gaps
A test gap was identified for the most critical scenario of the PR.

### Main gap
- There is no test guaranteeing that a task cancelled while still in the queue never reaches execution.

### Recommended test
Add an integration test that:
1. Enqueues a task
2. Cancels it before execution begins
3. Verifies that the processing callback was not executed
4. Verifies the final status is cancelled with no processing artifacts

## Residual risk if approved without changes
- High risk of unexpected behavior for cancellation
- Potential unnecessary operational cost
- Potential erosion of user trust among those relying on queue control

## Review decision
**Recommendation:** Request changes.

## Suggested fix checklist
- [ ] Remove a task by identifier in the unified queue
- [ ] Wire cancellation to real queue removal
- [ ] Defensive guard at the start of worker execution
- [ ] Fix the file open in the HTTP client
- [ ] New integration test for queue cancellation
- [ ] Run the test suite after the adjustments

## Conclusion
The PR's architectural direction is good and modernizes the project by centralizing processing in the API. With the fixes above, the change is likely to be solid in terms of functional contract, observability, and operational reliability.
