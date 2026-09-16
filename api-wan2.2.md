
    # 设置你的 API Key
    API_KEY="YOUR_API_KEY"
    
    curl --location --request POST "https://router.shengsuanyun.com/api/v1/tasks/generations" \
      --header "Content-Type: application/json" \
      --header "Authorization: Bearer ${API_KEY}" \
      --data '{
        "duration": 5,
        "first_frame_url": "https://oss.shengsuanyun.com/example/modelinfo/224/2025-11-11_17:46:01_input_1.png",
        "last_frame_url": "https://oss.shengsuanyun.com/example/modelinfo/224/2025-11-11_17:46:01_input_2.png",
        "model": "ali/wan2.2-kf2v-flash",
        "prompt": "一只黑色小猫好奇地看向天空，镜头从平视逐渐上升，过度平滑自然，最后俯拍小猫好奇的眼神。",
        "prompt_extend": true,
        "resolution": "720P" // 720P 和1080P
}'
    
    