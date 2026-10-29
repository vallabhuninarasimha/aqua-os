Add-Type -AssemblyName System.Drawing
$imgPath = "C:\Users\naras\.gemini\antigravity\brain\aa64cefb-1b87-4854-a6a9-6e0c332f3e9f\.user_uploaded\media_1793283968923_2659aa57.jpg"
$bmp = [System.Drawing.Bitmap]::FromFile($imgPath)
Write-Host "Width: $($bmp.Width), Height: $($bmp.Height)"
$bmp.Dispose()

