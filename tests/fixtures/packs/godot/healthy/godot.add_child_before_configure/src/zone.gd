extends Node
func spawn():
	var p = SCENE.instantiate()
	p.marker_path = $Markers.get_path()
	add_child(p)
