# gunicorn.py - 生产环境启动文件

import sys
import os

# 添加当前目录到路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from web_translator import app

if __name__ == "__main__":
    app.run()
