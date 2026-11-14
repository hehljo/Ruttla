extends Node
func spawn():
	var p = SCENE.instantiate()
	p.marker_path = $Markers.get_path()
	add_child(p)
	p.global_position = Vector3.ZERO # Needs the tree, so after add_child.
