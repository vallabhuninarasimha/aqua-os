Add-Type -AssemblyName System.Drawing

$src = "C:\Users\naras\.gemini\antigravity\brain\aa64cefb-1b87-4854-a6a9-6e0c332f3e9f\.user_uploaded\media_1793283968923_2659aa57.jpg"
$bmp = [System.Drawing.Bitmap]::FromFile($src)
$outDir = "C:\Users\naras\PyProjects\aqua-os\apps\dashboard\assets"

# Total 1024 x 682
# Panel 1: Top-Left (TV Wallboard)
# x: 0 to 576, y: 145 to 468 (Width: 576, Height: 323)
$r1 = [System.Drawing.Rectangle]::new(0, 145, 576, 323)
$c1 = $bmp.Clone($r1, $bmp.PixelFormat)
$c1.Save("$outDir\exact_panel1_tv.png", [System.Drawing.Imaging.ImageFormat]::Png)
$c1.Dispose()

# Panel 2: Top-Right (Owner Dashboard)
# x: 576 to 1024, y: 145 to 468 (Width: 448, Height: 323)
$r2 = [System.Drawing.Rectangle]::new(576, 145, 448, 323)
$c2 = $bmp.Clone($r2, $bmp.PixelFormat)
$c2.Save("$outDir\exact_panel2_owner.png", [System.Drawing.Imaging.ImageFormat]::Png)
$c2.Dispose()

# Panel 3: Bottom-Left (Worker Mobile)
# x: 0 to 550, y: 468 to 214 (Width: 550, Height: 214)
$r3 = [System.Drawing.Rectangle]::new(0, 468, 550, 214)
$c3 = $bmp.Clone($r3, $bmp.PixelFormat)
$c3.Save("$outDir\exact_panel3_worker.png", [System.Drawing.Imaging.ImageFormat]::Png)
$c3.Dispose()

# Panel 4: Bottom-Right (3D Pond View & Control)
# x: 550 to 1024, y: 468 to 214 (Width: 474, Height: 214)
$r4 = [System.Drawing.Rectangle]::new(550, 468, 474, 214)
$c4 = $bmp.Clone($r4, $bmp.PixelFormat)
$c4.Save("$outDir\exact_panel4_pond.png", [System.Drawing.Imaging.ImageFormat]::Png)
$c4.Dispose()

$bmp.Dispose()
Write-Host "All 4 exact panels cropped successfully!"

