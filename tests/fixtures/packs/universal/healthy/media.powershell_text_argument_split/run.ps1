# Start-Process $exe -ArgumentList @('--text', $text)
$text = 'Das sind mehrere Wörter.'
$quotedText = '"' + $text.Replace('"', '\"') + '"'
$arguments = @('--text', $quotedText, '--out', 'voice.wav')
Start-Process -FilePath $exe -ArgumentList $arguments -Wait
