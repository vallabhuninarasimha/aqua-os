Add-Type -AssemblyName System.Drawing
$src = "C:\Users\naras\.gemini\antigravity\brain\aa64cefb-1b87-4854-a6a9-6e0c332f3e9f\.user_uploaded\media_1793283968923_2659aa57.jpg"
$bmp = [System.Drawing.Bitmap]::FromFile($src)
$outDir = "C:\Users\naras\.gemini\antigravity\brain\aa64cefb-1b87-4854-a6a9-6e0c332f3e9f"

# Crop Top Header Banner (0 to 145)
$rTop = [System.Drawing.Rectangle]::new(0, 0, 1024, 145)
$cTop = $bmp.Clone($rTop, $bmp.PixelFormat)
$cTop.Save("$outDir\exact_header_banner.png", [System.Drawing.Imaging.ImageFormat]::Png)
$cTop.Dispose()

$bmp.Dispose()
Write-Host "Header banner cropped!"

