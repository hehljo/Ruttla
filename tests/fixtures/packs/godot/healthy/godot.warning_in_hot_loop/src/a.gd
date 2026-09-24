extends Node
var _warned := false
func _process(delta):
	if not target and not _warned:
		_warned = true
