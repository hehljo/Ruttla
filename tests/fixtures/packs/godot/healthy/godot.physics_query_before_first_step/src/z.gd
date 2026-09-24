extends Node
func spawn_all():
	await get_tree().physics_frame
	var s = get_world_3d().direct_space_state
	s.intersect_ray(q)
