import os
import requests
import logging
import json
import time
from typing import Optional, Dict, Any, Union

# Configuración de Logs
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

TOKEN_WHATSAPP = os.environ.get("WHATSAPP_TOKEN")

# --- RATE LIMITER ---
class RateLimiter:
    """Control de flujo 'Token Bucket' para evitar spam masivo."""
    def __init__(self, capacity: int = 10, refill_rate: int = 2, refill_time: int = 5) -> None:
        self.capacity = capacity
        self.tokens = capacity
        self.refill_rate = refill_rate
        self.refill_time = refill_time # seconds
        self.last_refill = time.time()
        
    def consume(self) -> bool:
        now = time.time()
        elapsed = now - self.last_refill
        
        if elapsed > self.refill_time:
            refills = int(elapsed / self.refill_time)
            self.tokens = min(self.capacity, self.tokens + (refills * self.refill_rate))
            self.last_refill = now
            
        if self.tokens >= 1:
            self.tokens -= 1
            return True
        return False

# Instancia global de Rate Limit (por número)
limiter_map: Dict[str, RateLimiter] = {}

def check_rate_limit(numero: str) -> bool:
    if numero not in limiter_map:
        limiter_map[numero] = RateLimiter()
    return limiter_map[numero].consume()

# --- WHATSAPP API ---

def enviar_whatsapp(numero: str, texto: str, url_media: Optional[str] = None) -> Optional[str]:
    """Envía mensaje a WhatsApp Cloud API (Texto o Imagen)."""
    try:
        phone_id = os.environ.get("META_PHONE_ID")
        url = f"https://graph.facebook.com/v18.0/{phone_id}/messages"
        headers = {
            "Authorization": f"Bearer {TOKEN_WHATSAPP}",
            "Content-Type": "application/json"
        }
        
        payload: Dict[str, Any] = {
            "messaging_product": "whatsapp",
            "to": numero,
            "type": "text"
        }
        
        if url_media:
            payload["type"] = "image"
            payload["image"] = {"link": url_media, "caption": texto}
        else:
            payload["text"] = {"body": texto}
            
        r = requests.post(url, headers=headers, json=payload)
        
        r = requests.post(url, headers=headers, json=payload)
        
        if r.status_code in [200, 201]:
            logging.info(f"📤 Respuesta enviada a {numero}")
            try:
                return r.json()["messages"][0]["id"]
            except:
                return "ID_NOT_FOUND"
        else:
            logging.error(f"❌ Error enviando WhatsApp: {r.text}")
            return None
            
    except Exception as e:
        logging.error(f"Error crítico enviando WhatsApp: {e}")
        return False

def descargar_media_meta(media_id: str) -> Optional[bytes]:
    """Obtiene el binario de un archivo multimedia (Foto/Audio) enviado por WhatsApp."""
    try:
        url_info = f"https://graph.facebook.com/v18.0/{media_id}"
        headers = {"Authorization": f"Bearer {TOKEN_WHATSAPP}"}
        
        # 1. Obtener URL de descarga
        r = requests.get(url_info, headers=headers)
        if r.status_code != 200:
            logging.error(f"Error obteniendo URL media: {r.text}")
            return None
            
        media_url = r.json().get("url")
        
        # 2. Descargar binario
        r_bin = requests.get(media_url, headers=headers)
        if r_bin.status_code == 200:
            return r_bin.content
        return None
    except Exception as e:
        logging.error(f"Error descargando media Meta: {e}")
        return None

def enviar_reporte_email(csv_data: str, destinatario: str = "glamstorechile2019@gmail.com") -> bool:
    """Envía el reporte de stock por email (Utility)."""
    # ... (Mover lógica de email también aquí o a un servicio aparte?)
    # Por simplicidad, dejemos email aquí ya que es "salida".
    DESTINATARIO = destinatario
    DESTINATARIO = destinatario
    SENDER = os.environ.get("EMAIL_SENDER") or os.environ.get("SMTP_USER")
    PASSWORD = os.environ.get("EMAIL_PASSWORD") or os.environ.get("SMTP_PASSWORD")
    
    if not SENDER or not PASSWORD:
        logging.error("Faltan credenciales de Email")
        return False

    try:
        msg = MIMEMultipart()
        msg['From'] = SENDER
        msg['To'] = DESTINATARIO
        msg['Subject'] = f"📊 Reporte GlamStore {time.strftime('%Y-%m-%d')}"
        
        body = "Adjunto el inventario actualizado."
        msg.attach(MIMEText(body, 'plain'))
        
        part = MIMEApplication(csv_data.encode('utf-8'), Name="inventario.csv")
        part['Content-Disposition'] = 'attachment; filename="inventario.csv"'
        msg.attach(part)
        
        # Usar puerto 465 (SSL) que es menos propenso a bloqueos que 587 (TLS start)
        server = smtplib.SMTP_SSL('smtp.gmail.com', 465)
        # server.starttls() # No necesario con SMTP_SSL
        server.login(SENDER, PASSWORD)
        server.send_message(msg)
        server.quit()
        return True
    except Exception as e:
        logging.error(f"Error email: {e}")
        return False

# Imports necesarios para email que no estaban arriba
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
