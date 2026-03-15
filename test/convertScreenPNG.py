from PIL import Image
import numpy as np
#
#sudo cat /dev/waveshare > /tmp/screenshot.raw
#
#
data = open("screenshot.raw", "rb").read()
arr = np.frombuffer(data, dtype=np.uint16).reshape((320, 480))
r = ((arr & 0xF800) >> 11) << 3
g = ((arr & 0x07E0) >> 5)  << 2
b = (arr  & 0x001F)         << 3
img = Image.fromarray(np.stack([r, g, b], axis=2).astype(np.uint8))
img.save("display.png")
print("saved display.png")