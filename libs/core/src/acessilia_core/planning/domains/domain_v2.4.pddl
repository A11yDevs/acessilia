;; Acessilia PDDL domain
;; Version 2.4 - obligation-oriented orchestration
;;
;; One problem instance represents one processing job for one document.
;; The canonical document graph, request metadata, obligation targets and
;; perceptual observations remain in the external manifest. PDDL receives
;; only the operational projection required for planning.
;;
;; The compiler selects the obligations that belong to the current plan and
;; computes their transitive predecessor closure before emitting the problem.
;;
;; Version 2.3 adds the Dr.DocBench PR #125 capabilities as first-class
;; obligation kinds (see domain_description_v2.3.md, section 2). The domain
;; structure is unchanged: the new kinds are ordinary `obligationkind`
;; symbols emitted by the compiler, with their own `supports`, `admissible`
;; and `execution-cost` entries. The nominal semantics of
;; `execute-obligation` remain identical.
;;
;; Version 2.4 adds the Toolbox catalogue snapshot to the problem (#640, PR 1;
;; ADR-0029): a method `requires` a capability on a provider, the snapshot
;; `offered` what it publishes, and `runnable` derives that every requirement
;; of an available method is offered. `execute-obligation` needs a runnable
;; method instead of an available one. `available` keeps meaning that the
;; core has a handler for the method; a method without Toolbox requirements
;; is runnable whenever it is available.

(define (domain acessilia-obligations)

  (:requirements
    :adl
    :typing
    :derived-predicates
    :action-costs
  )

  (:types
    obligation
    obligationkind
    method
    capability
    provider
  )

  (:predicates

    ;; Lifecycle of the single job represented by the problem instance.
    (queued)
    (processing)
    (completed)

    ;; Operational state of obligations.
    (kind-of ?o - obligation ?k - obligationkind)

    ;; The compiler marks as selected every obligation that must be completed,
    ;; including all transitive predecessors of the selected roots.
    (selected ?o - obligation)

    (pending ?o - obligation)
    (satisfied ?o - obligation)

    ;; Derived predicates are declared here and defined below.
    (ready ?o - obligation)
    (all-selected-satisfied)
    (causally-consistent)

    ;; (depends-on o predecessor) means that o can run only after its
    ;; predecessor has been satisfied.
    (depends-on ?o - obligation ?predecessor - obligation)

    ;; Method capabilities and per-obligation eligibility.
    (available ?m - method)
    (supports ?m - method ?k - obligationkind)
    (admissible ?m - method ?o - obligation)

    ;; Added by the runtime after an observed failure or rejected result.
    (tried ?o - obligation ?m - method)

    ;; Catalogue snapshot (2.4): what a method calls on the Toolbox, and what
    ;; the snapshot publishes. `runnable` is derived below.
    (requires ?m - method ?c - capability ?p - provider)
    (offered ?c - capability ?p - provider)
    (runnable ?m - method)
  )

  (:functions
    ;; Static, non-negative integer estimate supplied by the compiler.
    (execution-cost ?m - method ?o - obligation) - number
    (total-cost) - number
  )

  ;; An obligation is executable only if it belongs to the selected closure,
  ;; is still pending and every declared predecessor has been satisfied.
  (:derived (ready ?o - obligation)
    (and
      (selected ?o)
      (pending ?o)
      (forall (?pre - obligation)
        (or
          (not (depends-on ?o ?pre))
          (satisfied ?pre)
        )
      )
    )
  )

  ;; Completion is defined over the compiler-selected causal closure, not over
  ;; an ambiguous required/optional distinction.
  (:derived (all-selected-satisfied)
    (forall (?o - obligation)
      (or
        (not (selected ?o))
        (satisfied ?o)
      )
    )
  )

  ;; Defensive invariant for replanning states reconstructed by the runtime:
  ;; no satisfied obligation may have an unsatisfied direct predecessor.
  ;; Because the condition ranges over every satisfied obligation, it also
  ;; enforces transitive causal consistency.
  (:derived (causally-consistent)
    (forall (?o ?pre - obligation)
      (or
        (not (depends-on ?o ?pre))
        (not (satisfied ?o))
        (satisfied ?pre)
      )
    )
  )

  ;; A method is runnable when the core can run it and the catalogue snapshot
  ;; offers every capability and provider it requires.
  (:derived (runnable ?m - method)
    (and
      (available ?m)
      (forall (?c - capability ?p - provider)
        (or
          (not (requires ?m ?c ?p))
          (offered ?c ?p)
        )
      )
    )
  )

  (:action start-job
    :parameters ()
    :precondition (queued)
    :effect (and
      (processing)
      (not (queued))
    )
  )

  ;; This is a nominal classical-planning operator: its effect denotes a
  ;; successfully validated execution. The runtime commits the effect only
  ;; after the external method succeeds; otherwise it records (tried o m) and
  ;; generates a new problem for replanning.
  (:action execute-obligation
    :parameters (
      ?o - obligation
      ?k - obligationkind
      ?m - method
    )
    :precondition (and
      (processing)
      (ready ?o)
      (kind-of ?o ?k)
      (runnable ?m)
      (supports ?m ?k)
      (admissible ?m ?o)
      (not (tried ?o ?m))
    )
    :effect (and
      (satisfied ?o)
      (not (pending ?o))
      (increase (total-cost) (execution-cost ?m ?o))
    )
  )

  (:action complete-job
    :parameters ()
    :precondition (and
      (processing)
      (all-selected-satisfied)
      (causally-consistent)
    )
    :effect (and
      (completed)
      (not (processing))
    )
  )
)
