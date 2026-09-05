"""从 LungSight 透明品牌标识生成 Windows 多尺寸圆形应用图标。"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter

root = Path(__file__).resolve().parent
source = root.parents[1] / 'public' / 'lungsight-brand-transparent.png'
image = Image.open(source).convert('RGBA')
bbox = image.getchannel('A').getbbox()
if not bbox:
    raise SystemExit('Logo has no visible pixels')
image = image.crop(bbox)

canvas = Image.new('RGBA', (1024, 1024), (0, 0, 0, 0))
shadow = Image.new('RGBA', canvas.size, (0, 0, 0, 0))
ImageDraw.Draw(shadow).ellipse((76, 84, 948, 956), fill=(0, 7, 13, 150))
shadow = shadow.filter(ImageFilter.GaussianBlur(28))
canvas.alpha_composite(shadow)

draw = ImageDraw.Draw(canvas)
draw.ellipse((66, 66, 958, 958), fill=(5, 30, 38, 255), outline=(89, 229, 220, 255), width=18)
draw.ellipse((91, 91, 933, 933), outline=(78, 166, 178, 145), width=8)

image.thumbnail((756, 756), Image.Resampling.LANCZOS)
x = (1024 - image.width) // 2
y = (1024 - image.height) // 2
canvas.alpha_composite(image, (x, y))
canvas.save(root / 'app-icon-preview.png')
canvas.save(root / 'app-icon.ico', sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])
print(root / 'app-icon.ico')
