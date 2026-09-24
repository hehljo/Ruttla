import subprocess
subprocess.run(['audiocpp_cli', '--task', 'tts', '--max-tokens', '256', '--out', 'voice.wav'])
subprocess.run(['ffmpeg', '-i', 'voice.wav', '-filter_complex', 'amix=inputs=2', 'mix.wav'])
