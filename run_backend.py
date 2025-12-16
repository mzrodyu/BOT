import uvicorn
import sys
import os
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=None, help="端口号")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="监听地址")
    args = parser.parse_args()
    
    # 优先使用命令行参数，其次环境变量，最后默认值
    port = args.port or int(os.environ.get("PORT", 8000))
    
    uvicorn.run(
        "backend.main:app",
        host=args.host,
        port=port,
        reload=True
    )
