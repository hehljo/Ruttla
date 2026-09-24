extends Node
func go():
	await get_tree().create_timer(2.0).timeout
