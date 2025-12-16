import sys
import os
import shutil

# 自动清除Python缓存
def clear_pycache():
    root_dir = os.path.dirname(os.path.abspath(__file__))
    for dirpath, dirnames, filenames in os.walk(root_dir):
        if '__pycache__' in dirnames:
            cache_path = os.path.join(dirpath, '__pycache__')
            shutil.rmtree(cache_path, ignore_errors=True)
        for f in filenames:
            if f.endswith('.pyc'):
                os.remove(os.path.join(dirpath, f))
    print("[Startup] Cleared Python cache", flush=True)

clear_pycache()

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from bot.main import main

if __name__ == "__main__":
    main()
