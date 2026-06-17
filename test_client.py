#!/usr/bin/env python3
import sys
import os
import json
import base64
import time
import io

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def test_http_upload():
    print("=== 测试 HTTP 图片上传 ===")
    try:
        import requests
    except ImportError:
        print("请先安装 requests: pip install requests")
        return

    from PIL import Image

    img = Image.new("RGB", (640, 480), color=(73, 109, 137))
    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format="JPEG")
    image_bytes = img_byte_arr.getvalue()

    url = "http://localhost:8000/api/v1/photos/upload"
    files = {"file": ("test_photo.jpg", image_bytes, "image/jpeg")}
    data = {
        "camera_id": "camera_test_001",
        "captured_at": "2024-01-15T10:30:00Z",
    }

    try:
        resp = requests.post(url, files=files, data=data, timeout=30)
        if resp.status_code == 201:
            result = resp.json()
            print(f"上传成功! Photo ID: {result['id']}")
            print(f"  filename: {result['filename']}")
            print(f"  camera_id: {result['camera_id']}")
            print(f"  status: {result['status']}")
            print(f"  minio_object_key: {result['minio_object_key']}")
            return result["id"]
        else:
            print(f"上传失败: {resp.status_code} - {resp.text}")
    except requests.exceptions.ConnectionError:
        print("无法连接到 Ingestion Service (端口 8000)，请确认服务已启动")
    return None


def test_base64_upload():
    print("\n=== 测试 Base64 图片上传 ===")
    try:
        import requests
    except ImportError:
        print("请先安装 requests: pip install requests")
        return

    from PIL import Image

    img = Image.new("RGB", (320, 240), color=(255, 200, 100))
    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format="PNG")
    b64_data = base64.b64encode(img_byte_arr.getvalue()).decode("utf-8")

    url = "http://localhost:8000/api/v1/photos/upload-base64"
    data = {
        "camera_id": "camera_base64_002",
        "image_base64": f"data:image/png;base64,{b64_data}",
        "filename": "test_base64.png",
    }

    try:
        resp = requests.post(url, data=data, timeout=30)
        if resp.status_code == 201:
            result = resp.json()
            print(f"Base64上传成功! Photo ID: {result['id']}")
            return result["id"]
        else:
            print(f"上传失败: {resp.status_code} - {resp.text}")
    except requests.exceptions.ConnectionError:
        print("无法连接到 Ingestion Service (端口 8000)")
    return None


def test_mqtt_publish():
    print("\n=== 测试 MQTT 发布图片 ===")
    try:
        import paho.mqtt.publish as publish
        from PIL import Image

        img = Image.new("RGB", (800, 600), color=(50, 200, 50))
        img_byte_arr = io.BytesIO()
        img.save(img_byte_arr, format="JPEG")
        image_bytes = img_byte_arr.getvalue()

        payload = json.dumps({
            "camera_id": "camera_mqtt_003",
            "filename": "mqtt_test.jpg",
            "content_type": "image/jpeg",
            "captured_at": "2024-01-15T12:00:00Z",
            "image_base64": base64.b64encode(image_bytes).decode("utf-8"),
        })

        from common.config import settings

        publish.single(
            topic="camera/mqtt_test_003/photo",
            payload=payload,
            hostname=settings.MQTT_HOST,
            port=settings.MQTT_PORT,
            qos=1,
        )
        print("MQTT 消息已发布到 topic: camera/mqtt_test_003/photo")
        print("请检查 ingestion service 日志确认接收")
    except ImportError as e:
        print(f"缺少依赖: {e}")
    except Exception as e:
        print(f"MQTT 发布失败: {e}")


def query_stats():
    print("\n=== 查询统计信息 ===")
    try:
        import requests
        for name, port in [("Ingestion", 8000), ("Detection", 8001)]:
            try:
                resp = requests.get(f"http://localhost:{port}/api/v1/stats", timeout=5)
                if resp.status_code == 200:
                    stats = resp.json()
                    print(f"{name} Service 统计:")
                    print(f"  总照片数: {stats['total_photos']}")
                    print(f"  待检测: {stats['pending_count']}")
                    print(f"  空拍: {stats['empty_count']}")
                    print(f"  有动物: {stats['animal_count']}")
                    print(f"  未知: {stats['unknown_count']}")
                    print(f"  失败: {stats['failed_count']}")
            except requests.exceptions.ConnectionError:
                print(f"{name} Service (端口 {port}) 未连接")
    except ImportError:
        pass


def wait_for_detection(photo_id, max_wait=60):
    print(f"\n=== 等待照片 {photo_id} 检测完成 (最多{max_wait}秒) ===")
    try:
        import requests
    except ImportError:
        return

    for i in range(max_wait // 3 + 1):
        try:
            resp = requests.get(f"http://localhost:8000/api/v1/photos/{photo_id}", timeout=5)
            if resp.status_code == 200:
                photo = resp.json()
                print(f"  [{i*3}s] status={photo['status']}, category={photo['category']}, "
                      f"has_animal={photo['has_animal']}, confidence={photo['confidence']}")
                if photo["status"] in ("completed", "failed"):
                    print("检测完成!")
                    break
        except requests.exceptions.ConnectionError:
            pass
        time.sleep(3)


if __name__ == "__main__":
    print("CK2 空拍照片过滤系统 - 测试客户端")
    print("=" * 50)

    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        if cmd == "upload":
            test_http_upload()
        elif cmd == "base64":
            test_base64_upload()
        elif cmd == "mqtt":
            test_mqtt_publish()
        elif cmd == "stats":
            query_stats()
        elif cmd == "wait":
            if len(sys.argv) > 2:
                wait_for_detection(int(sys.argv[2]))
            else:
                print("用法: python test_client.py wait <photo_id>")
        elif cmd == "all":
            pid1 = test_http_upload()
            pid2 = test_base64_upload()
            test_mqtt_publish()
            time.sleep(2)
            query_stats()
            if pid1:
                wait_for_detection(pid1)
        else:
            print(f"未知命令: {cmd}")
            print("可用命令: upload | base64 | mqtt | stats | wait <id> | all")
    else:
        pid1 = test_http_upload()
        pid2 = test_base64_upload()
        test_mqtt_publish()
        time.sleep(2)
        query_stats()
        if pid1:
            wait_for_detection(pid1)
