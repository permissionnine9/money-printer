
    # 设置你的 API Key
    API_KEY="YOUR_API_KEY"
    
    curl --location --request POST "https://router.shengsuanyun.com/api/v1/tasks/generations" \
      --header "Content-Type: application/json" \
      --header "Authorization: Bearer ${API_KEY}" \
      --data '{
        "height": 936,
        "image_urls": [
                "https://oss.shengsuanyun.com/example/modelinfo/165/2025-09-23_16:34:54_input_1.png",
                "https://oss.shengsuanyun.com/example/modelinfo/165/2025-09-23_16:34:54_input_2.png"
        ],
        "model": "bytedance/jimeng_v40",
        "prompt": "生成1张女孩和奶牛玩偶在游乐园开心地坐过山车的图片，涵盖早晨、中午、晚上",
        "scale": 0.9,
        "size": "2k(16:9)",
        "width": 1664
}'
    