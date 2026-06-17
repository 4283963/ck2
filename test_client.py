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


def test_groups_crud():
    print("\n=== 测试 组别 CRUD ===")
    try:
        import requests
    except ImportError:
        print("请先安装 requests: pip install requests")
        return

    base = "http://localhost:8000/api/v1/groups"

    groups_data = [
        {"name": "黑熊出没区", "group_type": "area", "description": "疑似黑熊活动区域", "color": "#8B4513"},
        {"name": "鹿群聚集点", "group_type": "area", "description": "常见鹿群区域", "color": "#228B22"},
        {"name": "夜间红外照片", "group_type": "tag", "description": "红外相机夜间拍摄", "color": "#FF6347"},
        {"name": "待人工复核", "group_type": "custom", "description": "需要人工确认的可疑照片", "color": "#FFD700"},
    ]

    created_ids = []
    for gd in groups_data:
        try:
            resp = requests.post(base, json=gd, timeout=10)
            if resp.status_code == 201:
                g = resp.json()
                created_ids.append(g["id"])
                print(f"  创建组: id={g['id']}, name='{g['name']}', type={g['group_type']}, color={g['color']}")
            elif resp.status_code == 409:
                print(f"  跳过已存在: {gd['name']}")
            else:
                print(f"  创建失败 {gd['name']}: {resp.status_code} {resp.text}")
        except requests.exceptions.ConnectionError:
            print("无法连接到 Ingestion Service (端口 8000)")
            return

    print("\n  查询所有组别:")
    try:
        resp = requests.get(base, timeout=10)
        if resp.status_code == 200:
            groups = resp.json()
            for g in groups:
                print(f"    - [{g['group_type']}] {g['name']} (id={g['id']}, photos={g['photo_count']})")
    except requests.exceptions.ConnectionError:
        pass

    return created_ids


def test_batch_add_to_group(group_id=None, photo_ids=None):
    print(f"\n=== 测试 批量添加照片到组 ===")
    try:
        import requests
    except ImportError:
        return

    base = f"http://localhost:8000/api/v1/groups/{group_id}"

    if photo_ids is None:
        try:
            resp = requests.get("http://localhost:8000/api/v1/photos?limit=20", timeout=10)
            if resp.status_code == 200:
                photos = resp.json()
                photo_ids = [p["id"] for p in photos]
        except requests.exceptions.ConnectionError:
            print("无法连接到 Ingestion Service")
            return

    if not photo_ids:
        print("没有可用的照片，请先上传一些")
        return

    print(f"  目标组ID: {group_id}, 待添加照片数: {len(photo_ids)}")
    print(f"  照片ID列表: {photo_ids}")

    try:
        resp = requests.post(
            f"{base}/photos/batch-add",
            json={"photo_ids": photo_ids},
            timeout=10,
        )
        if resp.status_code == 200:
            result = resp.json()
            print(f"  添加结果: 成功 {result['added_count']} 张, 跳过 {result['skipped_count']} 张")
            if result["added_ids"]:
                print(f"  成功添加的ID: {result['added_ids']}")
        else:
            print(f"  请求失败: {resp.status_code} {resp.text}")
    except requests.exceptions.ConnectionError:
        print("无法连接到 Ingestion Service")


def test_filter_by_group(group_id):
    print(f"\n=== 测试 按组别筛选照片 ===")
    try:
        import requests
    except ImportError:
        return

    print(f"  只显示属于组ID={group_id}的照片:")
    try:
        resp = requests.get(
            f"http://localhost:8000/api/v1/photos",
            params={"group_id": group_id, "limit": 10},
            timeout=10,
        )
        if resp.status_code == 200:
            photos = resp.json()
            print(f"  返回 {len(photos)} 张照片:")
            for p in photos:
                groups = p.get("groups", [])
                group_names = ", ".join(g["name"] for g in groups)
                print(f"    - photo#{p['id']} {p['filename']}  组别: [{group_names}]")
    except requests.exceptions.ConnectionError:
        print("无法连接到 Ingestion Service")

    print(f"\n  排除组ID={group_id}的照片 (取反筛选):")
    try:
        resp = requests.get(
            f"http://localhost:8000/api/v1/photos",
            params={"exclude_group_id": group_id, "limit": 5},
            timeout=10,
        )
        if resp.status_code == 200:
            photos = resp.json()
            print(f"  返回 {len(photos)} 张不在组内的照片")
    except requests.exceptions.ConnectionError:
        pass


def test_groups_workflow():
    print("\n" + "=" * 60)
    print("CK2 区域分组 / 标签归堆 功能完整测试")
    print("=" * 60)

    pid1 = test_http_upload()
    pid2 = test_base64_upload()
    test_mqtt_publish()
    time.sleep(1)

    group_ids = test_groups_crud()
    if group_ids:
        target_group = group_ids[0]
        test_batch_add_to_group(group_id=target_group)
        test_filter_by_group(group_id=target_group)
    else:
        print("\n跳过分组测试（未能创建组别）")

    query_stats()


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
        elif cmd == "groups":
            test_groups_crud()
        elif cmd == "add-to-group":
            gid = int(sys.argv[2]) if len(sys.argv) > 2 else 1
            pids = [int(x) for x in sys.argv[3].split(",")] if len(sys.argv) > 3 else None
            test_batch_add_to_group(gid, pids)
        elif cmd == "filter-group":
            gid = int(sys.argv[2]) if len(sys.argv) > 2 else 1
            test_filter_by_group(gid)
        elif cmd == "group-test":
            test_groups_workflow()
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
            print("可用命令:")
            print("  upload | base64 | mqtt | stats")
            print("  wait <photo_id>")
            print("  groups              - 创建并查询组别")
            print("  add-to-group <gid> <pid1,pid2,...>   - 批量添加照片到组")
            print("  filter-group <gid>                    - 按组别筛选照片")
            print("  group-test                           - 完整分组功能测试")
            print("  all")
    else:
        pid1 = test_http_upload()
        pid2 = test_base64_upload()
        test_mqtt_publish()
        time.sleep(2)
        query_stats()
        if pid1:
            wait_for_detection(pid1)
