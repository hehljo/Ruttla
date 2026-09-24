@rpc("any_peer", "reliable")
func submit(data: Dictionary) -> void:
	var s := multiplayer.get_remote_sender_id()
	process_data(s, data)
