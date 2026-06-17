import json
import logging
import threading
from datetime import datetime
from typing import Optional

import paho.mqtt.client as mqtt

from common.config import settings
from common.database import SessionLocal
from ingestion_service.photo_service import (
    save_photo_to_db,
    parse_base64_image,
    extract_camera_id_from_topic,
    is_valid_content_type,
)

logger = logging.getLogger(__name__)


class MQTTPhotoListener:
    def __init__(self):
        self.client = None
        self._running = False
        self._thread = None

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            logger.info(f"MQTT connected successfully, subscribing to {settings.MQTT_TOPIC}")
            client.subscribe(settings.MQTT_TOPIC, qos=1)
        else:
            logger.error(f"MQTT connection failed with code {rc}")

    def _on_disconnect(self, client, userdata, rc):
        logger.warning(f"MQTT disconnected with code {rc}")
        if rc != 0:
            logger.info("MQTT unexpected disconnection, will try to reconnect...")

    def _on_message(self, client, userdata, msg):
        try:
            self._process_message(msg)
        except Exception as e:
            logger.exception(f"Error processing MQTT message from {msg.topic}: {e}")

    def _process_message(self, msg):
        topic = msg.topic
        payload = msg.payload
        logger.debug(f"Received MQTT message on {topic}, payload size: {len(payload)} bytes")

        try:
            message_data = json.loads(payload.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            logger.warning(f"Non-JSON payload on {topic}, treating as raw bytes")
            message_data = None

        db = SessionLocal()
        try:
            camera_id = extract_camera_id_from_topic(topic)
            image_bytes = None
            content_type = "image/jpeg"
            filename = f"mqtt_{camera_id}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.jpg"
            captured_at = None

            if message_data and isinstance(message_data, dict):
                camera_id = message_data.get("camera_id", camera_id)
                filename = message_data.get("filename", filename)
                content_type = message_data.get("content_type", content_type)
                captured_at_str = message_data.get("captured_at")
                if captured_at_str:
                    try:
                        captured_at = datetime.fromisoformat(captured_at_str.replace("Z", "+00:00"))
                    except ValueError:
                        logger.warning(f"Invalid captured_at format: {captured_at_str}")

                if "image_base64" in message_data:
                    image_bytes, detected_ct = parse_base64_image(message_data["image_base64"])
                    if detected_ct:
                        content_type = detected_ct
                elif "image" in message_data and isinstance(message_data["image"], str):
                    image_bytes, detected_ct = parse_base64_image(message_data["image"])
                    if detected_ct:
                        content_type = detected_ct
            else:
                image_bytes = payload

            if image_bytes is None:
                logger.error(f"No image data found in MQTT message on {topic}")
                return

            if not is_valid_content_type(content_type):
                logger.warning(f"Invalid content type {content_type}, defaulting to image/jpeg")
                content_type = "image/jpeg"

            photo = save_photo_to_db(
                db=db,
                camera_id=camera_id,
                filename=filename,
                content_type=content_type,
                image_bytes=image_bytes,
                source_channel="mqtt",
                mqtt_topic=topic,
                captured_at=captured_at,
            )
            logger.info(f"MQTT photo saved: id={photo.id}, camera={camera_id}")

        except Exception as e:
            logger.exception(f"Failed to save photo from MQTT: {e}")
            db.rollback()
        finally:
            db.close()

    def start(self):
        if self._running:
            return

        logger.info("Starting MQTT Photo Listener...")
        self.client = mqtt.Client(
            client_id=f"ingestion-service-{id(self)}",
            clean_session=True,
            protocol=mqtt.MQTTv311,
        )

        if settings.MQTT_USERNAME:
            self.client.username_pw_set(settings.MQTT_USERNAME, settings.MQTT_PASSWORD)

        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message
        self.client.reconnect_delay_set(min_delay=1, max_delay=30)

        try:
            self.client.connect(
                host=settings.MQTT_HOST,
                port=settings.MQTT_PORT,
                keepalive=60,
            )
        except Exception as e:
            logger.error(f"Failed to connect to MQTT broker at {settings.MQTT_HOST}:{settings.MQTT_PORT}: {e}")
            raise

        self._thread = threading.Thread(target=self._loop, name="mqtt-listener", daemon=True)
        self._thread.start()
        self._running = True
        logger.info("MQTT Photo Listener started")

    def _loop(self):
        try:
            self.client.loop_forever()
        except Exception as e:
            logger.exception(f"MQTT loop error: {e}")
        finally:
            self._running = False

    def stop(self):
        if self.client:
            self.client.disconnect()
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("MQTT Photo Listener stopped")


mqtt_listener = MQTTPhotoListener()
