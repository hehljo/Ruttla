import subprocess
subprocess.run(['audiocpp_cli', '--task', 'tts', '--out', 'voice.wav'])
raw_duration = duration('voice.wav')
if raw_duration < 0.2 or raw_duration > 30.0:
    raise RuntimeError('TTS duration invalid')
subprocess.run(['ffmpeg', '-i', 'voice.wav', '-filter_complex', 'amix=inputs=2', 'mix.wav'])
