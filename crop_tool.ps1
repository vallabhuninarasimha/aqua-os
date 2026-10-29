Add-Type -AssemblyName System.Drawing

$src = "C:\Users\naras\.gemini\antigravity\brain\aa64cefb-1b87-4854-a6a9-6e0c332f3e9f\.user_uploaded\media_1791996865298_7e13c14b.png"
$bmp = [System.Drawing.Bitmap]::new($src)

# Window inner dimensions:
# The 3D pond card starts below the Executive KPIs:
# Executive KPIs row: Y ≈ 140 to 195
# Pond 01 Digital Twin card: X ≈ 270, Y ≈ 200, Width ≈ 485, Height ≈ 192
# The 3D pond content inside: X ≈ 276, Y ≈ 220, Width ≈ 470, Height ≈ 165

$rect = [System.Drawing.Rectangle]::new(275, 201, 480, 185)
$cropped = $bmp.Clone($rect, $bmp.PixelFormat)
$cropped.Save("C:\Users\naras\PyProjects\aqua-os\apps\dashboard\assets\pond_digital_twin_card.png", [System.Drawing.Imaging.ImageFormat]::Png)
$cropped.Dispose()

# Also crop just the inner 3D pond water & aerators without text if possible
# Or keep the full card canvas
$rectInner = [System.Drawing.Rectangle]::new(277, 215, 455, 168)
$croppedInner = $bmp.Clone($rectInner, $bmp.PixelFormat)
$croppedInner.Save("C:\Users\naras\PyProjects\aqua-os\apps\dashboard\assets\pond_3d_viewport.png", [System.Drawing.Imaging.ImageFormat]::Png)
$croppedInner.Dispose()

$bmp.Dispose()
Write-Host "Pond assets cropped successfully."

