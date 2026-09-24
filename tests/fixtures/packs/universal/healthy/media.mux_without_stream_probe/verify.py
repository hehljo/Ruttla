import subprocess
probe = subprocess.run(['ffprobe', '-show_entries', 'stream=index:stream_tags=language,title', 'out.mkv'], capture_output=True, text=True)
if 'language=deu' not in probe.stdout:
    raise RuntimeError('stream language mismatch')
