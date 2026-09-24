extends Node
var t
func _ready():
	t = get_node("Target")
func _process(delta):
	t.position.x += delta
