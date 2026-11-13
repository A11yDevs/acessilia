.bypass_actors = (
  ((.bypass_actors // []) + [{"actor_id": 5, "actor_type": "RepositoryRole", "bypass_mode": "always"}])
  | unique_by([.actor_id, .actor_type])
)
