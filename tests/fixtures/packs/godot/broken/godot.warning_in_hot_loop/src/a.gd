extends Node
func _process(delta):
	if not target:
		push_warning("kein Ziel")
