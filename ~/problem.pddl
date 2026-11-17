(define (problem manifest-actionability)
  (:domain acessilia-obligations)

  (:objects
    o-1 - obligation
    describe-image - obligationkind
    human-review - method
  )

  (:init
    (queued)
    (= (total-cost) 0)
    (selected o-1)
    (kind-of o-1 describe-image)
    (pending o-1)
    (available human-review)
    (supports human-review describe-image)
    (admissible human-review o-1)
    (= (execution-cost human-review o-1) 5)
  )

  (:goal (completed))
  (:metric minimize (total-cost))
)
