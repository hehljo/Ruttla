import subprocess
subprocess.run(['ffmpeg', '-i', 'in.mkv', '-i', 'de.srt', '-map', '0:v', '-map', '0:s?', '-map', '1:s:0', 'out.mkv'])
