$text = 'Das sind mehrere Wörter.'
$arguments = @('--text', $text, '--out', 'voice.wav')
Start-Process -FilePath $exe -ArgumentList $arguments -Wait
