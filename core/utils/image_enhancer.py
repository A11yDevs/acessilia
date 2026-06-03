import cv2
import numpy as np
from PIL import Image
import io
from core.utils.logger import logger

VIT_PATCH_SIZE = 14
VIT_MAX_DIMENSION = 1344


def resize_for_vit(image_bytes: bytes) -> bytes:
    img = Image.open(io.BytesIO(image_bytes))
    if img.mode != "RGB":
        img = img.convert("RGB")
    w, h = img.size

    if w > VIT_MAX_DIMENSION or h > VIT_MAX_DIMENSION:
        ratio = VIT_MAX_DIMENSION / max(w, h)
        w, h = int(w * ratio), int(h * ratio)

    new_w = (w // VIT_PATCH_SIZE) * VIT_PATCH_SIZE
    new_h = (h // VIT_PATCH_SIZE) * VIT_PATCH_SIZE

    if (new_w, new_h) != (w, h):
        img = img.resize((new_w, new_h), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=95)
        logger.debug("Imagem redimensionada para ViT: {}x{} -> {}x{}", w, h, new_w, new_h)
        return buf.getvalue()

    return image_bytes

def enhance_image_for_ocr(image_bytes: bytes) -> bytes:
    try:
        nparr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        
        if img is None:
            return image_bytes

        img = cv2.fastNlMeansDenoisingColored(img, None, 10, 10, 7, 21)

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        coords = np.column_stack(np.where(gray > 0))
        angle = cv2.minAreaRect(coords)[-1]
        
        if angle < -45:
            angle = -(90 + angle)
        else:
            angle = -angle
            
        if abs(angle) > 0.5:
            (h, w) = img.shape[:2]
            center = (w // 2, h // 2)
            M = cv2.getRotationMatrix2D(center, angle, 1.0)
            img = cv2.warpAffine(img, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
            logger.debug("Imagem rotacionada em {:.2f} graus", angle)

        lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)
        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8,8))
        cl = clahe.apply(l)
        limg = cv2.merge((cl, a, b))
        img = cv2.cvtColor(limg, cv2.COLOR_LAB2BGR)

        _, buffer = cv2.imencode('.jpg', img, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
        return buffer.tobytes()

    except Exception as e:
        logger.error("Erro no pré-processamento de imagem: {}", e)
        return image_bytes

def is_math_likely(text: str) -> bool:
    math_indicators = ['=', '+', '-', '*', '/', '^', '√', '∫', '∑', 'π', 'θ', '²', '³', 'log', 'sin', 'cos', 'tan']
    count = sum(1 for indicator in math_indicators if indicator in text)
    return count > 2
