extends Node
func spawn():
	var p = SCENE.instantiate()
	add_child(p)
	p.marker_path = $Markers.get_path()
